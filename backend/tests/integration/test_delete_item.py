from uuid import UUID, uuid7

import pytest
from sqlalchemy import func, select

from grocery.db.models import Event
from grocery.db.session import unit_of_work
from grocery.domain.enums import EventType
from grocery.domain.errors import ItemNotFoundError
from grocery.schemas.items import AddItems, ItemCreate
from grocery.schemas.sources import AppSource
from grocery.services import shopping_list_service as service
from grocery.services.auth import acting_as, create_user

PHONE = AppSource(device_id="phone")


async def test_delete_by_id_records_one_event(shopping_list_id: UUID) -> None:
    async with unit_of_work() as db:
        added = await service.add_items(
            AddItems(shopping_list_id=shopping_list_id, items=[ItemCreate(name="Лук")]), PHONE
        )
        await service.delete_item(added[0].item.id, PHONE)
        assert await service.get_items(shopping_list_id) == []
        assert (
            await db.scalar(
                select(func.count()).select_from(Event).where(Event.type == EventType.ITEMS_DELETED)
            )
            == 1
        )


async def test_delete_hides_foreign_and_missing_items(shopping_list_id: UUID) -> None:
    async with unit_of_work() as db:
        other = await create_user("boris", "password")
        with acting_as(other):
            other_list = await service.get_default_shopping_list_id()
            added = await service.add_items(
                AddItems(shopping_list_id=other_list, items=[ItemCreate(name="Чай")]), PHONE
            )
        for item_id in (added[0].item.id, uuid7()):
            with pytest.raises(ItemNotFoundError):
                await service.delete_item(item_id, PHONE)
        assert await db.scalar(select(func.count()).select_from(Event)) == 1
        with acting_as(other):
            assert len(await service.get_items(other_list)) == 1
