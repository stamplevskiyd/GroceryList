from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from grocery.db.models import Item
from grocery.db.repositories.shopping import item_repo
from grocery.db.session import unit_of_work
from grocery.schemas.items import AddItems, ItemCreate, ItemUpdate
from grocery.schemas.sources import AppSource
from grocery.services import shopping_list_service as service

SOURCE = AppSource(device_id="phone")


async def test_tag_only_patch_changes_timestamp_and_event(shopping_list_id: UUID) -> None:
    async with unit_of_work() as db:
        created = (
            await service.add_items(
                AddItems(shopping_list_id=shopping_list_id, items=[ItemCreate(name="Лук")]), SOURCE
            )
        )[0].item
        stored = await db.get(Item, created.id)
        assert stored is not None
        old = datetime.now(UTC) - timedelta(days=1)
        stored.updated_at = old
    async with unit_of_work():
        changed = await service.update_item(created.id, ItemUpdate(tags=["Овощи"]), SOURCE)
        assert changed.updated_at > old
        assert changed.tags[0].name == "Овощи"
    async with unit_of_work():
        assert (await service.get_items(shopping_list_id))[0].updated_at == changed.updated_at


async def test_delete_tag_uses_cascade_and_refreshes_loaded_items(shopping_list_id: UUID) -> None:
    async with unit_of_work() as db:
        created = (
            await service.add_items(
                AddItems(
                    shopping_list_id=shopping_list_id,
                    items=[ItemCreate(name="Лук", tags=["Овощи", "Рецепт"])],
                ),
                SOURCE,
            )
        )[0].item
        loaded = await item_repo.get(created.id)
        assert loaded is not None
        old = datetime.now(UTC) - timedelta(days=1)
        loaded.updated_at = old
        await db.flush()
        vegetable = next(tag for tag in loaded.tags if tag.name == "Овощи")
        await service.delete_tag(vegetable.id, SOURCE)
        assert [tag.name for tag in loaded.tags] == ["Рецепт"]
        assert loaded.updated_at > old
        assert len(list(await db.scalars(select(Item)))) == 1


async def test_unicode_limits_roundtrip_in_postgres(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        item = (
            await service.add_items(
                AddItems(
                    shopping_list_id=shopping_list_id,
                    items=[
                        ItemCreate(
                            name="İ" * 127, quantity=Decimal(1), unit="İ" * 32, tags=["İ" * 127]
                        )
                    ],
                ),
                SOURCE,
            )
        )[0].item
    async with unit_of_work():
        stored = (await service.get_items(shopping_list_id))[0]
        assert stored.name == item.name
        assert stored.unit is not None
        assert len(stored.unit) == 64
        assert stored.tags[0].name == "İ" * 127
