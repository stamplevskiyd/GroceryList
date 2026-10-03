import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from grocery.main import create_app
from grocery.services.auth.rate_limit import get_login_limiter


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None


@pytest.fixture(autouse=True)
def fresh_limiter() -> Iterator[None]:
    get_login_limiter.cache_clear()
    yield
    get_login_limiter.cache_clear()


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    app = create_app()
    ready, stop = asyncio.Event(), asyncio.Event()

    async def run_manager() -> None:
        async with app.state.mcp.session_manager.run():
            ready.set()
            await stop.wait()

    task = asyncio.create_task(run_manager())
    await asyncio.wait_for(ready.wait(), 10)
    try:
        yield app
    finally:
        stop.set()
        await task


@pytest.fixture
async def rest(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        yield client


@pytest.fixture
async def credentials(rest: httpx.AsyncClient) -> dict[str, str]:
    from grocery.db.session import unit_of_work
    from grocery.services.auth import create_user

    async with unit_of_work():
        await create_user("anna", "password")
    logged = await rest.post(
        "/api/auth/login",
        json={"username": "anna", "password": "password"},
        headers={"X-Device-Id": "phone"},
    )
    assert logged.status_code == 200
    response = await rest.post(
        "/api/tokens", json={"name": "Test assistant"}, headers={"X-Device-Id": "phone"}
    )
    assert response.status_code == 200
    return {
        "token": response.json()["token"],
        "id": response.json()["id"],
        "list": logged.json()["shopping_lists"][0]["id"],
    }


@pytest.fixture
async def mcp(app: FastAPI, credentials: dict[str, str]) -> AsyncIterator[Client]:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        headers={"Authorization": "Bearer " + credentials["token"]},
    ) as http:
        # The Client task group must enter and exit in the test's own task.
        yield Client(streamable_http_client("https://testserver/mcp", http_client=http), cache=None)
