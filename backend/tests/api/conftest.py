"""API-тесты: приложение через ASGITransport, изоляция БД фикстурой db."""

from collections.abc import AsyncIterator, Iterator
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from grocery.db.session import unit_of_work
from grocery.main import create_app
from grocery.schemas.items import AddItems, ItemCreate, ItemRead
from grocery.schemas.sources import AppSource
from grocery.services import auth
from grocery.services import shopping_list_service as service
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


@pytest.fixture
async def login_and_list(client: httpx.AsyncClient, registered_user: None) -> UUID:
    response = await client.post(
        "/api/auth/login",
        headers={"X-Device-Id": "phone"},
        json={"username": "anna", "password": "test-password"},
    )
    assert response.status_code == 200
    return UUID(response.json()["shopping_lists"][0]["id"])


@pytest.fixture
async def foreign_item() -> ItemRead:
    async with unit_of_work():
        other = await auth.create_user("boris", "test-password")
        with auth.acting_as(other):
            shopping_list_id = await service.get_default_shopping_list_id()
            results = await service.add_items(
                AddItems(
                    shopping_list_id=shopping_list_id,
                    items=[ItemCreate(name="Чай", tags=["Завтрак"])],
                ),
                AppSource(device_id="other-phone"),
            )
            return results[0].item
