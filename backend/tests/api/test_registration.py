"""Public sign-up creates an isolated list and session in one transaction."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from grocery.config import get_settings
from grocery.db.models import Session, ShoppingList, ShoppingListMember, User
from grocery.db.repositories.users import user_repo
from grocery.db.session import unit_of_work
from grocery.services import auth

HEADERS = {"X-Device-Id": "signup-browser"}
BODY = {"username": "new-user", "password": "a-long-test-password"}


async def test_signup_creates_session_and_private_list(
    client: httpx.AsyncClient, registered_user: None
) -> None:
    response = await client.post("/api/auth/register", headers=HEADERS, json=BODY)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert all(
        part in cookie for part in ("__Host-gl_session=", "HttpOnly", "Secure", "SameSite=lax")
    )
    assert "Domain=" not in cookie
    me = response.json()
    assert me["username"] == "new-user"
    assert len(me["shopping_lists"]) == 1
    assert me["shopping_lists"][0]["name"] == "Покупки"
    assert "password" not in response.text
    assert "token" not in response.text
    assert (await client.get("/api/me")).json() == me
    async with unit_of_work() as session:
        user = await user_repo.by_username("new-user")
        assert user is not None
        assert await auth.verify_password(BODY["password"], user.password_hash)
        other = await user_repo.by_username("anna")
        assert other is not None
        foreign = await session.scalar(
            select(ShoppingList).where(ShoppingList.owner_id == other.id)
        )
        assert foreign is not None
        foreign_id = str(foreign.id)
        membership = await session.scalar(
            select(ShoppingListMember).where(ShoppingListMember.user_id == user.id)
        )
        assert membership is not None
        assert str(membership.shopping_list_id) == me["shopping_lists"][0]["id"]
    assert (
        await client.get("/api/items", params={"shopping_list_id": foreign_id})
    ).status_code == 404
    assert (await client.post("/api/auth/logout", headers=HEADERS)).status_code == 204
    assert (await client.post("/api/auth/login", headers=HEADERS, json=BODY)).status_code == 200


async def test_duplicate_does_not_replace_existing_session(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/auth/register", headers=HEADERS, json=BODY)).status_code == 201
    first = client.cookies["__Host-gl_session"]
    response = await client.post(
        "/api/auth/register", headers=HEADERS, json={**BODY, "username": " new-user "}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "set-cookie" not in response.headers
    assert client.cookies["__Host-gl_session"] == first
    async with unit_of_work() as session:
        for model in (User, ShoppingList, ShoppingListMember, Session):
            assert await session.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "   "},
        {"username": "x" * 65},
        {"password": "short"},
        {"password": "x" * 129},
        {"password": " " * 12},
        {"role": "admin"},
    ],
)
async def test_invalid_signup_writes_nothing(
    client: httpx.AsyncClient, changes: dict[str, str]
) -> None:
    response = await client.post("/api/auth/register", headers=HEADERS, json={**BODY, **changes})
    assert response.status_code == 422
    assert BODY["password"] not in response.text
    assert "set-cookie" not in response.headers
    async with unit_of_work() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_signup_requires_device(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/register", json=BODY)
    assert response.status_code == 422
    async with unit_of_work() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_signup_ip_limit(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_LOGIN_IP_LIMIT", "2")
    get_settings.cache_clear()
    for i in range(2):
        assert (
            await client.post(
                "/api/auth/register", headers=HEADERS, json={**BODY, "username": f"new{i}"}
            )
        ).status_code == 201
    response = await client.post(
        "/api/auth/register", headers={**HEADERS, "X-Forwarded-For": "192.0.2.2"}, json=BODY
    )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    assert "set-cookie" not in response.headers


async def test_session_failure_rolls_back_user_and_list(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Session failure")

    monkeypatch.setattr(auth, "issue_session", fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://testserver",
    ) as client:
        response = await client.post("/api/auth/register", headers=HEADERS, json=BODY)
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    async with unit_of_work() as session:
        for model in (User, ShoppingList, ShoppingListMember, Session):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.real_commits
async def test_concurrent_signup_returns_one_created_and_one_conflict(app: FastAPI) -> None:
    async def signup() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver"
        ) as client:
            return await client.post("/api/auth/register", headers=HEADERS, json=BODY)

    responses = await asyncio.gather(signup(), signup())
    assert sorted(response.status_code for response in responses) == [201, 409]
    async with unit_of_work() as session:
        for model in (User, ShoppingList, ShoppingListMember, Session):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
