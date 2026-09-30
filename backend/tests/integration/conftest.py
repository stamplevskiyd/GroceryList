"""Интеграционные тесты: каждый изолирован фикстурой db."""

from collections.abc import Iterator
from uuid import UUID

import pytest

from grocery.db.models import User
from grocery.db.session import unit_of_work
from grocery.services import shopping_list_service as service
from grocery.services.auth import acting_as, create_user


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None


@pytest.fixture
async def owner() -> User:
    async with unit_of_work():
        return await create_user("anna", "password")


@pytest.fixture
def authenticated(owner: User) -> Iterator[None]:
    with acting_as(owner):
        yield


@pytest.fixture
async def shopping_list_id(authenticated: None) -> UUID:
    async with unit_of_work():
        return await service.get_default_shopping_list_id()
