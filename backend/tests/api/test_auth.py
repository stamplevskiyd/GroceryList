"""Cookie login/logout/me use the public HTTP contract and real PostgreSQL."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grocery.config import get_settings
from grocery.db.models import Session
from grocery.db.repositories.sessions import session_repo
from grocery.db.session import unit_of_work
from grocery.services.auth.sessions import token_hash

COOKIE = "__Host-gl_session"
LOGIN = {"username": "anna", "password": "test-password"}
HEADERS = {"X-Device-Id": "phone"}


async def test_login_cookie_and_me(client: httpx.AsyncClient, registered_user: None) -> None:
    response = await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie
    assert "Max-Age=2592000" in cookie
    assert response.json()["username"] == "anna"
    assert len(response.json()["shopping_lists"]) == 1
    assert "password" not in response.text
    assert "token" not in response.text
    assert (await client.get("/api/me")).json() == response.json()
    token = client.cookies[COOKIE]
    async with unit_of_work():
        session = await session_repo.by_token_hash(token_hash(token))
        assert session is not None
        assert session.device_id == "phone"
        assert session.token_hash != token
    response = await client.post("/api/auth/logout", headers=HEADERS)
    assert response.status_code == 204
    assert response.content == b""
    cookie = response.headers["set-cookie"]
    assert "Max-Age=0" in cookie
    assert "Path=/" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Domain=" not in cookie
    async with unit_of_work():
        assert await session_repo.by_token_hash(token_hash(token)) is None
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.post("/api/auth/logout", headers=HEADERS)).status_code == 401


async def test_invalid_credentials_are_indistinguishable(
    client: httpx.AsyncClient, registered_user: None
) -> None:
    responses = [
        await client.post("/api/auth/login", headers=HEADERS, json=body)
        for body in (
            {"username": "anna", "password": "wrong-private-password"},
            {"username": "unknown", "password": "wrong-private-password"},
        )
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.json() == {
            "code": "invalid_credentials",
            "message": "Неверный логин или пароль",
        }
        assert "set-cookie" not in response.headers
        assert "www-authenticate" not in response.headers
    assert responses[0].json() == responses[1].json()


@pytest.mark.parametrize("state", ["missing", "random", "expired", "revoked"])
async def test_invalid_sessions_are_401(
    client: httpx.AsyncClient, registered_user: None, state: str
) -> None:
    if state != "missing":
        assert (
            await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)
        ).status_code == 200
        token = client.cookies[COOKIE]
        if state == "random":
            client.cookies.clear()
            client.cookies.set(COOKIE, "random-token")
        else:
            async with unit_of_work():
                session = await session_repo.by_token_hash(token_hash(token))
                assert session is not None
                if state == "expired":
                    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                else:
                    await session_repo.delete(session)
    response = await client.get("/api/me")
    assert response.status_code == 401
    assert response.json() == {"code": "not_authenticated", "message": "Требуется вход"}
    assert "www-authenticate" not in response.headers


async def test_repeated_login_issues_new_token_and_logout_only_revokes_current(
    client: httpx.AsyncClient, registered_user: None
) -> None:
    assert (await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)).status_code == 200
    first = client.cookies[COOKIE]
    assert (await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)).status_code == 200
    second = client.cookies[COOKIE]
    assert first != second
    # A later header identifies the mutation source, not a second authentication factor.
    assert (
        await client.post("/api/auth/logout", headers={"X-Device-Id": "laptop"})
    ).status_code == 204
    client.cookies.set(COOKIE, first)
    assert (await client.get("/api/me")).status_code == 200
    async with unit_of_work():
        assert await session_repo.by_token_hash(token_hash(first)) is not None
        assert await session_repo.by_token_hash(token_hash(second)) is None


async def test_login_requires_device_header(
    client: httpx.AsyncClient, registered_user: None
) -> None:
    response = await client.post("/api/auth/login", json=LOGIN)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert "set-cookie" not in response.headers
    assert ["header", "X-Device-Id"] in [detail["loc"] for detail in response.json()["details"]]


async def test_device_header_is_trimmed(client: httpx.AsyncClient, registered_user: None) -> None:
    response = await client.post(
        "/api/auth/login", headers={"X-Device-Id": " " + "x" * 128 + " "}, json=LOGIN
    )
    assert response.status_code == 200
    async with unit_of_work():
        session = await session_repo.by_token_hash(token_hash(client.cookies[COOKIE]))
        assert session is not None
        assert session.device_id == "x" * 128


async def test_login_rejects_body_source(client: httpx.AsyncClient, registered_user: None) -> None:
    response = await client.post(
        "/api/auth/login",
        headers=HEADERS,
        json={**LOGIN, "source": {"kind": "app", "device_id": "spoofed"}},
    )
    assert response.status_code == 422
    assert response.json()["details"][0]["loc"] == ["body", "source"]
    assert "test-password" not in response.text
    assert "spoofed" not in response.text


async def test_successes_count_towards_username_limit(
    client: httpx.AsyncClient, registered_user: None
) -> None:
    for _ in range(5):
        assert (
            await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)
        ).status_code == 200
    response = await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)
    assert response.status_code == 429
    assert response.json() == {
        "code": "too_many_attempts",
        "message": "Слишком много попыток входа",
    }
    assert int(response.headers["retry-after"]) >= 1
    assert "set-cookie" not in response.headers


async def test_forwarded_header_cannot_bypass_ip_limit(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_LOGIN_IP_LIMIT", "2")
    get_settings.cache_clear()
    for i in range(2):
        response = await client.post(
            "/api/auth/login",
            headers={**HEADERS, "X-Forwarded-For": f"192.0.2.{i}"},
            json={"username": f"unknown{i}", "password": "bad"},
        )
        assert response.status_code == 401
    response = await client.post(
        "/api/auth/login",
        headers={**HEADERS, "X-Forwarded-For": "192.0.2.100"},
        json={"username": "other", "password": "bad"},
    )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1


async def test_commit_failure_cannot_send_success_cookie_or_body(
    app: FastAPI, registered_user: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_commit(session: AsyncSession) -> None:
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post("/api/auth/login", headers=HEADERS, json=LOGIN)
    assert response.status_code == 500
    assert response.json() == {"code": "internal_error", "message": "Внутренняя ошибка"}
    assert "set-cookie" not in response.headers
    assert "anna" not in response.text
    monkeypatch.undo()
    async with unit_of_work() as session:
        assert await session.scalar(select(func.count()).select_from(Session)) == 0
