"""Protocol flows exercise committed PostgreSQL state, not mocked repositories."""

import asyncio
import base64
import hashlib
from collections.abc import Iterator
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from grocery.api.routers.oauth import public_limiter
from grocery.db.models.oauth import OAuthCode, OAuthGrant, OAuthToken
from grocery.db.repositories.oauth import client_repo, oauth_token_repo
from grocery.db.session import unit_of_work
from grocery.mcp_server.verifier import GroceryTokenVerifier
from grocery.schemas.oauth import ClientDocument
from grocery.services.auth import cimd, oauth
from grocery.services.auth.sessions import token_hash

VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)
HEADERS = {"X-Device-Id": "test-browser"}
RESOURCE = "http://testserver/mcp"
REDIRECT = "http://127.0.0.1:9876/callback?source=test"


@pytest.fixture(autouse=True)
def fresh_oauth_limiter() -> Iterator[None]:
    public_limiter.cache_clear()
    yield
    public_limiter.cache_clear()


async def registration(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/oauth/register",
        json={
            "client_name": "Test assistant",
            "redirect_uris": ["http://127.0.0.1:1234/callback?source=test"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["client_id"])


def authorization_params(client_id: str, **changes: str) -> dict[str, str]:
    return {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
        "scope": "shopping_list offline_access",
        "state": "state + & = юникод",
        **changes,
    }


async def start(client: httpx.AsyncClient, client_id: str, **changes: str) -> str:
    response = await client.get(
        "/oauth/authorize", params={**authorization_params(client_id), **changes}
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/consent?request=")
    assert "HttpOnly" in response.headers["set-cookie"]
    return parse_qs(urlsplit(response.headers["location"]).query)["request"][0]


async def code_for(client: httpx.AsyncClient, client_id: str, **changes: str) -> str:
    request_id = await start(client, client_id, **changes)
    info = await client.get("/api/oauth/requests/" + request_id)
    assert info.status_code == 200, info.text
    assert info.json()["loopback"] is True
    response = await client.post(
        "/api/oauth/consent", headers=HEADERS, json={"request_id": request_id, "allow": True}
    )
    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["redirect_url"]).query)
    assert query["iss"] == ["http://testserver"]
    assert query["state"] == ["state + & = юникод"]
    assert query["source"] == ["test"]
    return str(query["code"][0])


def exchange_data(client_id: str, code: str, **changes: str) -> dict[str, str]:
    return {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT,
        "resource": RESOURCE,
        "code_verifier": VERIFIER,
        **changes,
    }


async def issue(client: httpx.AsyncClient, client_id: str, **changes: str) -> dict[str, str]:
    code = await code_for(client, client_id, **changes)
    response = await client.post("/oauth/token", data=exchange_data(client_id, code))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()  # type: ignore[no-any-return]


def refresh_data(client_id: str, raw: str) -> dict[str, str]:
    return {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": raw,
        "resource": RESOURCE,
    }


async def test_metadata(client: httpx.AsyncClient) -> None:
    response = await client.get("/.well-known/oauth-authorization-server")
    body = response.json()
    assert body["issuer"] == "http://testserver"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert body["client_id_metadata_document_supported"] is True
    assert body["authorization_response_iss_parameter_supported"] is True
    assert response.headers["access-control-allow-origin"] == "*"
    assert (await client.options("/oauth/token")).status_code == 204


async def test_dcr_flow_rotation_revoke_and_hashes(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    client_id = await registration(client)
    first = await issue(client, client_id)
    identity = await GroceryTokenVerifier().verify_token(first["access_token"])
    assert identity is not None
    assert identity.client_id == client_id
    assert identity.claims == {"client_name": "Test assistant"}
    second_response = await client.post(
        "/oauth/token", data=refresh_data(client_id, first["refresh_token"])
    )
    assert second_response.status_code == 200
    second = second_response.json()
    assert first["access_token"] != second["access_token"]
    assert first["refresh_token"] != second["refresh_token"]
    async with unit_of_work() as session:
        tokens = list(await session.scalars(select(OAuthToken)))
        assert len(tokens) == 2
        assert all(
            len(t.access_token_hash) == len(t.refresh_token_hash or "") == 64 for t in tokens
        )
        assert first["access_token"] not in {t.access_token_hash for t in tokens}
        code = await session.scalar(select(OAuthCode))
        assert code is not None
        assert len(code.token_hash) == 64
        assert code.consumed_at is not None
    # Wrong public client cannot revoke another client's refresh family.
    await client.post(
        "/oauth/revoke", data={"client_id": "wrong", "token": second["refresh_token"]}
    )
    assert await GroceryTokenVerifier().verify_token(second["access_token"]) is not None
    response = await client.post(
        "/oauth/revoke", data={"client_id": client_id, "token": second["refresh_token"]}
    )
    assert response.status_code == 200
    assert await GroceryTokenVerifier().verify_token(first["access_token"]) is None
    assert await GroceryTokenVerifier().verify_token(second["access_token"]) is None
    assert (
        await client.post("/oauth/token", data=refresh_data(client_id, second["refresh_token"]))
    ).status_code == 400
    assert (await client.get("/api/oauth/connections")).json() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"code_verifier": "x" * 64},
        {"client_id": "other"},
        {"redirect_uri": "http://127.0.0.1:9999/callback?source=test"},
        {"resource": "https://evil.test/mcp"},
        {"code_verifier": "short"},
    ],
)
async def test_exchange_binding_does_not_consume_valid_code(
    client: httpx.AsyncClient, login_and_list: UUID, changes: dict[str, str]
) -> None:
    client_id = await registration(client)
    code = await code_for(client, client_id)
    assert (
        await client.post("/oauth/token", data={**exchange_data(client_id, code), **changes})
    ).status_code == 400
    response = await client.post("/oauth/token", data=exchange_data(client_id, code))
    assert response.status_code == 200
    assert (
        await client.post("/oauth/token", data=exchange_data(client_id, code))
    ).status_code == 400
    assert await GroceryTokenVerifier().verify_token(response.json()["access_token"]) is None


@pytest.mark.real_commits
async def test_refresh_race_and_late_replay_commits_family_revocation(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    client_id = await registration(client)
    first = await issue(client, client_id)
    data = refresh_data(client_id, first["refresh_token"])
    responses = await asyncio.gather(
        client.post("/oauth/token", data=data), client.post("/oauth/token", data=data)
    )
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["refresh_token"] != responses[1].json()["refresh_token"]
    async with unit_of_work():
        old = await oauth_token_repo.by_hash(token_hash(first["refresh_token"]), refresh=True)
        assert old is not None
        old.rotated_at = oauth.now() - timedelta(seconds=61)
    assert (await client.post("/oauth/token", data=data)).json()["error"] == "invalid_grant"
    # Separate transactions prove the error response did not roll back the revoke.
    for response in responses:
        assert await GroceryTokenVerifier().verify_token(response.json()["access_token"]) is None
        assert (
            await client.post(
                "/oauth/token", data=refresh_data(client_id, response.json()["refresh_token"])
            )
        ).status_code == 400


@pytest.mark.real_commits
async def test_concurrent_code_exchange_is_single_use(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    client_id = await registration(client)
    code = await code_for(client, client_id)
    results = await asyncio.gather(
        *(client.post("/oauth/token", data=exchange_data(client_id, code)) for _ in range(2))
    )
    assert sorted(r.status_code for r in results) == [200, 400]


async def test_browser_binding_deny_and_no_device_id(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    client_id = await registration(client)
    request_id = await start(client, client_id)
    payload = {"request_id": request_id, "allow": True}
    assert (await client.post("/api/oauth/consent", json=payload)).status_code == 422
    cookie = next(c for c in client.cookies.jar if c.name.startswith("__Host-gl_oauth_"))
    raw = cookie.value
    assert raw is not None
    client.cookies.delete(cookie.name, domain=cookie.domain, path=cookie.path)
    assert (await client.get("/api/oauth/requests/" + request_id)).status_code == 400
    assert (
        await client.post("/api/oauth/consent", headers=HEADERS, json=payload)
    ).status_code == 400
    client.cookies.set(cookie.name, raw, domain=cookie.domain, path=cookie.path)
    response = await client.post(
        "/api/oauth/consent", headers=HEADERS, json={**payload, "allow": False}
    )
    query = parse_qs(urlsplit(response.json()["redirect_url"]).query)
    assert query["error"] == ["access_denied"]
    assert query["iss"] == ["http://testserver"]
    assert "code" not in query
    async with unit_of_work() as session:
        assert await session.scalar(select(OAuthCode)) is None
    assert (
        await client.post("/api/oauth/consent", headers=HEADERS, json=payload)
    ).status_code == 400


@pytest.mark.parametrize(
    "changes",
    [
        {"redirect_uri": "https://evil.test/cb"},
        {"redirect_uri": "http://localhost:9876/callback?source=test"},
        {"client_id": "unknown"},
    ],
)
async def test_invalid_callback_never_redirects(
    client: httpx.AsyncClient, changes: dict[str, str]
) -> None:
    client_id = await registration(client)
    response = await client.get(
        "/oauth/authorize", params={**authorization_params(client_id), **changes}
    )
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"resource": "https://evil.test/mcp"}, "invalid_target"),
        ({"scope": "admin"}, "invalid_scope"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": "bad"}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
    ],
)
async def test_authorize_errors_preserve_state_and_issuer(
    client: httpx.AsyncClient, changes: dict[str, str], error: str
) -> None:
    client_id = await registration(client)
    response = await client.get(
        "/oauth/authorize", params={**authorization_params(client_id), **changes}
    )
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == [error]
    assert query["iss"] == ["http://testserver"]
    assert query["state"] == ["state + & = юникод"]


async def test_access_only_and_disconnect_all_grants(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    client_id = await registration(client)
    first = await issue(client, client_id, scope="shopping_list")
    assert "refresh_token" not in first
    second = await issue(client, client_id)
    connections = (await client.get("/api/oauth/connections")).json()
    assert len(connections) == 1
    assert connections[0]["client_name"] == "Test assistant"
    await client.post(
        "/oauth/revoke", data={"client_id": client_id, "token": second["access_token"]}
    )
    assert await GroceryTokenVerifier().verify_token(second["access_token"]) is None
    assert (
        await client.post("/oauth/token", data=refresh_data(client_id, second["refresh_token"]))
    ).status_code == 200
    response = await client.delete(
        "/api/oauth/connections/" + connections[0]["id"], headers=HEADERS
    )
    assert response.status_code == 204
    assert await GroceryTokenVerifier().verify_token(first["access_token"]) is None
    assert (await client.get("/api/oauth/connections")).json() == []


async def test_cimd_flow_and_cache(
    client: httpx.AsyncClient, login_and_list: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = "https://assistant.example/oauth/client.json"
    calls = []

    async def fetch(url: str) -> tuple[ClientDocument, int]:
        calls.append(url)
        return ClientDocument(
            client_id=url, client_name="CIMD assistant", redirect_uris=[REDIRECT]
        ), 300

    monkeypatch.setattr(cimd, "fetch_document", fetch)
    first = await issue(client, client_id)
    await issue(client, client_id)
    assert calls == [client_id]
    identity = await GroceryTokenVerifier().verify_token(first["access_token"])
    assert identity is not None
    assert identity.client_id == client_id
    async with unit_of_work():
        stored = await client_repo.by_client_id(client_id)
        assert stored is not None
        stored.cache_expires_at = oauth.now() - timedelta(seconds=1)
    await start(client, client_id)
    assert calls == [client_id, client_id]


async def test_expiry_and_audience(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    client_id = await registration(client)
    first = await issue(client, client_id)
    async with unit_of_work() as session:
        grant = await session.scalar(select(OAuthGrant))
        assert grant is not None
        grant.resource = "https://other.example/mcp"
    assert await GroceryTokenVerifier().verify_token(first["access_token"]) is None
    async with unit_of_work() as session:
        grant = await session.scalar(select(OAuthGrant))
        assert grant is not None
        grant.resource = RESOURCE
        grant.expires_at = oauth.now() - timedelta(seconds=1)
    assert (
        await client.post("/oauth/token", data=refresh_data(client_id, first["refresh_token"]))
    ).status_code == 400
    assert await GroceryTokenVerifier().verify_token(first["access_token"]) is None


async def test_bounded_protocol_requests(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oauth/token",
        content="grant_type=a&grant_type=b",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert (await client.post("/oauth/token", json={})).status_code == 400
    assert (
        await client.post(
            "/oauth/register", content="x" * 65537, headers={"Content-Type": "application/json"}
        )
    ).status_code == 400
    assert (await client.get("/oauth/authorize?client_id=a&client_id=b")).status_code == 400
    response = await client.post(
        "/oauth/register", json={"client_name": "bad", "redirect_uris": ["javascript:alert(1)"]}
    )
    assert response.status_code == 400


async def test_pending_request_is_bound_to_first_user(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    from grocery.services.auth import create_user

    client_id = await registration(client)
    request_id = await start(client, client_id)
    assert (await client.get("/api/oauth/requests/" + request_id)).status_code == 200
    async with unit_of_work():
        await create_user("other-oauth-user", "password")
    await client.post(
        "/api/auth/login",
        headers=HEADERS,
        json={"username": "other-oauth-user", "password": "password"},
    )
    response = await client.post(
        "/api/oauth/consent", headers=HEADERS, json={"request_id": request_id, "allow": True}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "access_denied"


async def test_disconnect_is_user_scoped(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    from grocery.services.auth import create_user

    client_id = await registration(client)
    token = await issue(client, client_id)
    connection = (await client.get("/api/oauth/connections")).json()[0]
    async with unit_of_work():
        await create_user("other-oauth-user", "password")
    await client.post(
        "/api/auth/login",
        headers=HEADERS,
        json={"username": "other-oauth-user", "password": "password"},
    )
    assert (await client.get("/api/oauth/connections")).json() == []
    assert (
        await client.delete("/api/oauth/connections/" + connection["id"], headers=HEADERS)
    ).status_code == 404
    assert await GroceryTokenVerifier().verify_token(token["access_token"]) is not None


async def test_expired_request_code_and_access(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    from grocery.db.models.oauth import OAuthAuthorizationRequest

    client_id = await registration(client)
    request_id = await start(client, client_id)
    async with unit_of_work() as session:
        request = await session.get(OAuthAuthorizationRequest, UUID(request_id))
        assert request is not None
        request.expires_at = oauth.now() - timedelta(seconds=1)
    assert (await client.get("/api/oauth/requests/" + request_id)).status_code == 400
    assert (
        await client.post(
            "/api/oauth/consent", headers=HEADERS, json={"request_id": request_id, "allow": True}
        )
    ).status_code == 400
    code = await code_for(client, client_id)
    async with unit_of_work() as session:
        stored = await session.scalar(
            select(OAuthCode).where(OAuthCode.token_hash == token_hash(code))
        )
        assert stored is not None
        stored.expires_at = oauth.now() - timedelta(seconds=1)
    assert (
        await client.post("/oauth/token", data=exchange_data(client_id, code))
    ).status_code == 400
    pair = await issue(client, client_id)
    async with unit_of_work():
        token = await oauth_token_repo.by_hash(token_hash(pair["access_token"]))
        assert token is not None
        token.expires_at = oauth.now() - timedelta(seconds=1)
    assert await GroceryTokenVerifier().verify_token(pair["access_token"]) is None
    assert (
        await client.post("/oauth/token", data=refresh_data(client_id, pair["refresh_token"]))
    ).status_code == 200


@pytest.mark.real_commits
async def test_disconnect_racing_refresh_cannot_resurrect_grant(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    client_id = await registration(client)
    pair = await issue(client, client_id)
    connection = (await client.get("/api/oauth/connections")).json()[0]
    refreshed, disconnected = await asyncio.gather(
        client.post("/oauth/token", data=refresh_data(client_id, pair["refresh_token"])),
        client.delete("/api/oauth/connections/" + connection["id"], headers=HEADERS),
    )
    assert disconnected.status_code == 204
    assert refreshed.status_code in (200, 400)
    if refreshed.status_code == 200:
        assert await GroceryTokenVerifier().verify_token(refreshed.json()["access_token"]) is None
    assert await GroceryTokenVerifier().verify_token(pair["access_token"]) is None
    assert (
        await client.post("/oauth/token", data=refresh_data(client_id, pair["refresh_token"]))
    ).status_code == 400
