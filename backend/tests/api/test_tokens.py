from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI


async def test_token_lifecycle(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    created = await client.post(
        "/api/tokens", json={"name": "Code"}, headers={"X-Device-Id": "phone"}
    )
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    token = created.json()
    assert token["token"].startswith("gl_pat_")
    listed = await client.get("/api/tokens")
    assert listed.headers["cache-control"] == "no-store"
    assert "token" not in listed.json()[0]
    assert "token_hash" not in listed.json()[0]
    for _ in range(2):
        deleted = await client.delete(
            f"/api/tokens/{token['id']}", headers={"X-Device-Id": "phone"}
        )
        assert deleted.status_code == 204
        assert deleted.headers["cache-control"] == "no-store"
    assert (await client.get("/api/tokens")).json()[0]["revoked_at"] is not None
    assert (
        await client.delete(f"/api/tokens/{uuid7()}", headers={"X-Device-Id": "phone"})
    ).status_code == 404


@pytest.mark.parametrize(
    "body", [{"name": " "}, {"name": ""}, {"name": "x" * 256}, {"name": "Code", "user_id": "fake"}]
)
async def test_invalid_name(
    client: httpx.AsyncClient, login_and_list: UUID, body: dict[str, str]
) -> None:
    assert (
        await client.post("/api/tokens", json=body, headers={"X-Device-Id": "phone"})
    ).status_code == 422


async def test_cookie_and_device_required(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    assert (await client.post("/api/tokens", json={"name": "Code"})).status_code == 422
    client.cookies.clear()
    assert (
        await client.get("/api/tokens", headers={"Authorization": "Bearer gl_pat_fake"})
    ).status_code == 401


@pytest.mark.real_commits
async def test_pat_issue_commit_failure_does_not_reveal_secret(
    app: FastAPI, client: httpx.AsyncClient, login_and_list: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from grocery.db.models import PersonalAccessToken
    from grocery.db.session import unit_of_work

    async def fail_commit(session: AsyncSession) -> None:
        raise RuntimeError("forced commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_commit)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="https://testserver",
            cookies=client.cookies,
        ) as failed_client:
            response = await failed_client.post(
                "/api/tokens", json={"name": "Code"}, headers={"X-Device-Id": "phone"}
            )
    assert response.status_code == 500
    assert "gl_pat_" not in response.text
    async with unit_of_work() as db:
        assert list(await db.scalars(select(PersonalAccessToken))) == []


async def test_cannot_list_or_revoke_another_users_token(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    from grocery.db.session import unit_of_work
    from grocery.schemas.tokens import TokenCreate
    from grocery.services.auth import acting_as, create_user
    from grocery.services.auth.tokens import issue_token

    async with unit_of_work():
        other = await create_user("boris", "password")
        with acting_as(other):
            token = await issue_token(TokenCreate(name="Boris"))
    assert (await client.get("/api/tokens")).json() == []
    response = await client.delete(f"/api/tokens/{token.id}", headers={"X-Device-Id": "phone"})
    missing = await client.delete(f"/api/tokens/{uuid7()}", headers={"X-Device-Id": "phone"})
    assert response.status_code == missing.status_code == 404
    assert response.json() == missing.json()
