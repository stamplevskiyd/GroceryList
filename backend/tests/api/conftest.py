"""API-тесты: приложение через ASGITransport, изоляция БД фикстурой db."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from grocery.main import create_app


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport не выполняет lifespan: движок БД подменяет фикстура db.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
