"""API-тесты: приложение через ASGITransport, изоляция БД фикстурой db."""

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI

from grocery.db.session import unit_of_work
from grocery.main import create_app
from grocery.services import auth
from grocery.services.auth.rate_limit import get_login_limiter


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None


@pytest.fixture(autouse=True)
def _fresh_login_limiter() -> Iterator[None]:
    get_login_limiter.cache_clear()
    yield
    get_login_limiter.cache_clear()


@pytest.fixture
async def registered_user() -> None:
    async with unit_of_work():
        await auth.create_user("anna", "test-password")


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport не выполняет lifespan: движок БД подменяет фикстура db.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        yield client
