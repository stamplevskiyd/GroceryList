import asyncio
from decimal import Decimal
from uuid import UUID, uuid7

import pytest
from sqlalchemy import func, select

from grocery.db.models import Event, Item, User
from grocery.db.session import unit_of_work
from grocery.domain.enums import AddStatus, EventType
from grocery.domain.errors import ItemNotFoundError, NotFoundError
from grocery.schemas.events import ItemsPayload
from grocery.schemas.items import AddItems, ItemCreate, ItemUpdate, QuickAdd
from grocery.schemas.sources import AppSource, McpSource
from grocery.services import shopping_list_service as service
from grocery.services.auth import acting_as, create_user

PHONE = AppSource(device_id="phone")
CLAUDE = McpSource(client_id="claude", client_name="Claude")


async def test_batch_merge_and_one_event(shopping_list_id: UUID) -> None:
    async with unit_of_work() as session:
        results = await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[
                    ItemCreate(
                        name="Зелёный лук",
                        quantity=Decimal("1"),
                        unit="кг",
                        tags=["Для супа"],
                        note="красный",
                    ),
                    ItemCreate(
                        name=" зеленый  ЛУК ",
                        quantity=Decimal("500"),
                        unit="гр",
                        tags=["Овощи"],
                        note="крупный",
                    ),
                ],
            ),
            PHONE,
        )
        assert [r.status for r in results] == [AddStatus.CREATED, AddStatus.MERGED]
        item = results[1].item
        assert item.id == results[0].item.id
        assert item.name == "Зелёный лук"
        assert item.quantity == Decimal("1500")
        assert {tag.name for tag in item.tags} == {"Для супа", "Овощи"}
        assert item.note == "красный; крупный"
        assert item.created_at == results[0].item.created_at
        assert await session.scalar(select(func.count()).select_from(Event)) == 1
    async with unit_of_work():
        merged = await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[ItemCreate(name="Зеленый лук", quantity=Decimal("1"), unit="г")],
            ),
            CLAUDE,
        )
        assert merged[0].item.quantity == Decimal("1501")
        assert [s.model_dump() for s in merged[0].item.sources] == [
            {"kind": "app"},
            {"kind": "mcp", "client_name": "Claude"},
        ]


async def test_bought_and_incompatible_units_do_not_merge(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        first = (
            await service.add_items(
                AddItems(
                    shopping_list_id=shopping_list_id,
                    items=[ItemCreate(name="Лук", unit="г"), ItemCreate(name="Лук", unit="шт")],
                ),
                PHONE,
            )
        )[0].item
        await service.set_bought(shopping_list_id, [first.id], True, PHONE)
        result = await service.add_items(
            AddItems(shopping_list_id=shopping_list_id, items=[ItemCreate(name="Лук", unit="г")]),
            PHONE,
        )
        assert result[0].status == AddStatus.CREATED
        assert len(await service.get_items(shopping_list_id)) == 2
        assert len(await service.get_items(shopping_list_id, include_bought=True)) == 3


async def test_quick_add_and_patch_nulls(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        added = await service.quick_add(
            QuickAdd(shopping_list_id=shopping_list_id, text="молоко 2л", tags=["Завтрак"]), PHONE
        )
        assert added.parsed.quantity == Decimal("2000")
        item = await service.update_item(
            added.result.item.id, ItemUpdate(note="безлактозное"), PHONE
        )
        assert item.quantity == Decimal("2000")
        item = await service.update_item(
            item.id, ItemUpdate(quantity=None, unit=None, note=None, tags=[]), PHONE
        )
        assert (item.quantity, item.unit, item.note, item.tags) == (None, None, None, [])
        assert (await service.list_tags(shopping_list_id))[0].open_count == 0


async def test_patch_unit_conversion(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        item = (
            await service.add_items(
                AddItems(
                    shopping_list_id=shopping_list_id,
                    items=[ItemCreate(name="Лук", quantity=Decimal("1"), unit="шт")],
                ),
                PHONE,
            )
        )[0].item
        updated = await service.update_item(
            item.id, ItemUpdate(quantity=Decimal("1.5"), unit="кг"), PHONE
        )
        assert (updated.quantity, updated.unit) == (Decimal("1500"), "г")


async def test_set_bought_idempotent_and_clear_preserves_history(shopping_list_id: UUID) -> None:
    async with unit_of_work() as session:
        first, second = await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[ItemCreate(name="Лук"), ItemCreate(name="Молоко")],
            ),
            PHONE,
        )
        bought = await service.set_bought(
            shopping_list_id, [first.item.id, first.item.id], True, PHONE
        )
        timestamp = bought[0].bought_at
        assert timestamp is not None
        repeated = await service.set_bought(shopping_list_id, [first.item.id], True, PHONE)
        assert repeated[0].bought_at == timestamp
        assert await service.clear_bought(shopping_list_id, PHONE) == 1
        assert [item.id for item in await service.get_items(shopping_list_id)] == [second.item.id]
        event = await session.scalar(select(Event).where(Event.type == EventType.BOUGHT_CLEARED))
        assert event is not None
        assert isinstance(event.payload, ItemsPayload)
        assert event.payload.items[0].name == "Лук"
        assert event.payload.items[0].bought_at == timestamp


async def test_tag_rename_merge_delete_and_bulk(shopping_list_id: UUID) -> None:
    async with unit_of_work() as session:
        await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[
                    ItemCreate(name="Лук", tags=["Для супа", "Овощи"]),
                    ItemCreate(name="Морковь", tags=["Овощи"]),
                ],
            ),
            PHONE,
        )
        tags = {tag.name: tag for tag in await service.list_tags(shopping_list_id)}
        renamed = await service.rename_tag(tags["Для супа"].id, "овощи", PHONE)
        assert renamed.id == tags["Овощи"].id
        assert len(await service.list_tags(shopping_list_id)) == 1
        assert all(len(item.tags) == 1 for item in await service.get_items(shopping_list_id))
        assert (
            await session.scalar(
                select(func.count()).select_from(Event).where(Event.type == EventType.TAGS_MERGED)
            )
            == 1
        )
        await service.bulk_tag(renamed.id, "mark_bought", PHONE)
        assert (await service.list_tags(shopping_list_id))[0].open_count == 0
        await service.delete_tag(renamed.id, PHONE)
        assert all(
            not item.tags for item in await service.get_items(shopping_list_id, include_bought=True)
        )


async def test_bulk_delete_and_unused_tag_persists(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[ItemCreate(name="Лук", tags=["Суп"]), ItemCreate(name="Чай")],
            ),
            PHONE,
        )
        tag = (await service.list_tags(shopping_list_id))[0]
        assert await service.bulk_tag(tag.id, "delete_items", PHONE) == 1
        assert [item.name for item in await service.get_items(shopping_list_id)] == ["Чай"]
        assert (await service.list_tags(shopping_list_id))[0].open_count == 0


async def test_bad_id_rolls_back_whole_batch(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        item = (
            await service.add_items(
                AddItems(shopping_list_id=shopping_list_id, items=[ItemCreate(name="Лук")]), PHONE
            )
        )[0].item
    with pytest.raises(ItemNotFoundError):
        async with unit_of_work():
            await service.set_bought(shopping_list_id, [item.id, uuid7()], True, PHONE)
    async with unit_of_work():
        assert (await service.get_items(shopping_list_id))[0].is_bought is False


async def test_unbought_and_delete_by_tag_have_one_event_each(shopping_list_id: UUID) -> None:
    async with unit_of_work() as session:
        added = await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[ItemCreate(name="Лук", tags=["Суп"]), ItemCreate(name="Чай")],
            ),
            PHONE,
        )
        await service.set_bought(shopping_list_id, [added[0].item.id], True, PHONE)
        restored = await service.set_bought(shopping_list_id, [added[0].item.id], False, PHONE)
        assert restored[0].bought_at is None
        assert restored[0].is_bought is False
        assert await service.remove_items(shopping_list_id, PHONE, tag=" СУП ") == 1
        assert [item.name for item in await service.get_items(shopping_list_id)] == ["Чай"]
        types = list(await session.scalars(select(Event.type).order_by(Event.id)))
        assert types == [
            EventType.ITEMS_ADDED,
            EventType.ITEMS_BOUGHT,
            EventType.ITEMS_UNBOUGHT,
            EventType.ITEMS_DELETED,
        ]


async def test_rename_without_merge_and_item_order(shopping_list_id: UUID) -> None:
    async with unit_of_work():
        added = await service.add_items(
            AddItems(
                shopping_list_id=shopping_list_id,
                items=[ItemCreate(name="Лук", tags=["Суп"]), ItemCreate(name="Чай")],
            ),
            PHONE,
        )
        assert [item.name for item in await service.get_items(shopping_list_id)] == ["Чай", "Лук"]
        renamed = await service.rename_tag(added[0].item.tags[0].id, "  Для  борща ", PHONE)
        assert renamed.name == "Для борща"
        await service.set_bought(shopping_list_id, [added[0].item.id], True, PHONE)
        await service.set_bought(shopping_list_id, [added[1].item.id], True, PHONE)
        assert [
            item.name for item in await service.get_items(shopping_list_id, include_bought=True)
        ] == ["Чай", "Лук"]


@pytest.mark.parametrize(
    "operation",
    [
        "get",
        "tags",
        "add",
        "quick",
        "update",
        "bought",
        "remove",
        "clear",
        "rename",
        "delete_tag",
        "bulk",
    ],
)
async def test_every_operation_hides_other_users_objects(
    shopping_list_id: UUID, operation: str
) -> None:
    async with unit_of_work():
        other_user = await create_user("boris", "password")
        with acting_as(other_user):
            other_id = await service.get_default_shopping_list_id()
            item = (
                await service.add_items(
                    AddItems(
                        shopping_list_id=other_id, items=[ItemCreate(name="Лук", tags=["Суп"])]
                    ),
                    PHONE,
                )
            )[0].item
            tag_id = item.tags[0].id
        with pytest.raises(NotFoundError):  # noqa: PT012 — матрица изоляции операций
            match operation:
                case "get":
                    await service.get_items(other_id)
                case "tags":
                    await service.list_tags(other_id)
                case "add":
                    await service.add_items(
                        AddItems(shopping_list_id=other_id, items=[ItemCreate(name="Чай")]), PHONE
                    )
                case "quick":
                    await service.quick_add(QuickAdd(shopping_list_id=other_id, text="чай"), PHONE)
                case "update":
                    await service.update_item(item.id, ItemUpdate(name="Чай"), PHONE)
                case "bought":
                    await service.set_bought(shopping_list_id, [item.id], True, PHONE)
                case "remove":
                    await service.remove_items(shopping_list_id, PHONE, ids=[item.id])
                case "clear":
                    await service.clear_bought(other_id, PHONE)
                case "rename":
                    await service.rename_tag(tag_id, "Новое", PHONE)
                case "delete_tag":
                    await service.delete_tag(tag_id, PHONE)
                case "bulk":
                    await service.bulk_tag(tag_id, "mark_bought", PHONE)


@pytest.mark.real_commits
async def test_concurrent_adds_merge_without_lost_quantity(
    shopping_list_id: UUID, owner: User
) -> None:
    async def add() -> None:
        with acting_as(owner):
            async with unit_of_work():
                await service.add_items(
                    AddItems(
                        shopping_list_id=shopping_list_id,
                        items=[ItemCreate(name="Лук", quantity=Decimal("1"), tags=["Суп"])],
                    ),
                    PHONE,
                )

    await asyncio.wait_for(asyncio.gather(add(), add()), timeout=10)
    async with unit_of_work() as session:
        items = await service.get_items(shopping_list_id)
        assert len(items) == 1
        assert items[0].quantity == Decimal("2")
        assert await session.scalar(select(func.count()).select_from(Item)) == 1
        assert await session.scalar(select(func.count()).select_from(Event)) == 2
