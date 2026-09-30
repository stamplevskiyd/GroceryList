"""Одна бизнес-логика для REST и MCP (ADR-0008). Коммит принадлежит вызывающему UoW."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from grocery.db.models import Item, Tag
from grocery.db.repositories.shopping import item_repo, shopping_list_repo, tag_repo
from grocery.db.session import get_current_session
from grocery.domain.enums import AddStatus, EventType
from grocery.domain.errors import (
    ErrorDetail,
    InvalidInputError,
    ItemNotFoundError,
    ShoppingListNotFoundError,
    TagNotFoundError,
)
from grocery.domain.normalization import normalize_name, normalize_quantity
from grocery.domain.quick_add import parse_quick_add
from grocery.schemas.events import EventPayload
from grocery.schemas.items import (
    AddItemResult,
    AddItems,
    ItemCreate,
    ItemRead,
    ItemUpdate,
    ParsedItem,
    QuickAdd,
    QuickAddResult,
    TagRead,
)
from grocery.schemas.sources import Source, item_source
from grocery.schemas.tags import TagCreate, TagUpdate, TagUsageRead
from grocery.services.auth import get_current_user
from grocery.services.events import record_event
from grocery.services.shopping_list_service.merge import merge_item


async def ensure_shopping_list_access(shopping_list_id: UUID, *, lock: bool = False) -> None:
    if not await shopping_list_repo.has_member(shopping_list_id, get_current_user().id):
        raise ShoppingListNotFoundError()
    if lock and await shopping_list_repo.lock(shopping_list_id) is None:
        raise ShoppingListNotFoundError()


async def get_default_shopping_list_id() -> UUID:
    lists = await shopping_list_repo.for_user(get_current_user().id)
    if not lists:
        raise ShoppingListNotFoundError()
    if len(lists) != 1:
        raise InvalidInputError("Укажите shopping_list_id: доступно несколько списков")
    return lists[0].id


async def _item_for_update(id: UUID) -> Item:
    item = await item_repo.get(id)
    if item is None or not await shopping_list_repo.has_member(
        item.shopping_list_id, get_current_user().id
    ):
        raise ItemNotFoundError()
    await ensure_shopping_list_access(item.shopping_list_id, lock=True)
    # Перечитать после ожидания lock: другая транзакция могла изменить/удалить позицию.
    item = await item_repo.get(id)
    if item is None:
        raise ItemNotFoundError()
    return item


async def _tag_for_update(id: UUID) -> Tag:
    tag = await tag_repo.get(id)
    if tag is None or not await shopping_list_repo.has_member(
        tag.shopping_list_id, get_current_user().id
    ):
        raise TagNotFoundError()
    await ensure_shopping_list_access(tag.shopping_list_id, lock=True)
    # populate_existing позволяет не использовать устаревший объект identity map.
    from sqlalchemy import select

    tag = await get_current_session().scalar(
        select(Tag).where(Tag.id == id).execution_options(populate_existing=True)
    )
    if tag is None:
        raise TagNotFoundError()
    return tag


async def _resolve_tags(shopping_list_id: UUID, names: Sequence[str]) -> list[Tag]:
    tags: list[Tag] = []
    seen: set[str] = set()
    for name in names:
        normalized = normalize_name(name)
        if normalized in seen:
            continue
        seen.add(normalized)
        tag = await tag_repo.by_name(shopping_list_id, normalized)
        if tag is None:
            tag = await tag_repo.add(TagCreate(name=name, shopping_list_id=shopping_list_id))
        tags.append(tag)
    return tags


async def get_items(shopping_list_id: UUID, *, include_bought: bool = False) -> list[ItemRead]:
    await ensure_shopping_list_access(shopping_list_id)
    return [
        ItemRead.model_validate(item)
        for item in await item_repo.for_shopping_list(
            shopping_list_id, include_bought=include_bought
        )
    ]


async def add_items(data: AddItems, source: Source) -> list[AddItemResult]:
    await ensure_shopping_list_access(data.shopping_list_id, lock=True)
    results: list[AddItemResult] = []
    for incoming in data.items:
        match = await item_repo.find_open_by_name(
            data.shopping_list_id, incoming.name_normalized, incoming.unit
        )
        tags = await _resolve_tags(data.shopping_list_id, incoming.tags)
        if match is None:
            match = await item_repo.add(
                incoming,
                shopping_list_id=data.shopping_list_id,
                sources=[item_source(source)],
                tags=tags,
            )
            status = AddStatus.CREATED
        else:
            await item_repo.update(match, merge_item(match, incoming, source))
            current_ids = {tag.id for tag in match.tags}
            match.tags = [*match.tags, *(tag for tag in tags if tag.id not in current_ids)]
            await get_current_session().flush()
            status = AddStatus.MERGED
        results.append(AddItemResult(status=status, item=ItemRead.model_validate(match)))
    await record_event(
        data.shopping_list_id, EventType.ITEMS_ADDED, source, EventPayload(results=results)
    )
    return results


async def quick_add(data: QuickAdd, source: Source) -> QuickAddResult:
    await ensure_shopping_list_access(data.shopping_list_id)
    parsed = parse_quick_add(data.text)
    try:
        incoming = ItemCreate(
            name=parsed.name, quantity=parsed.quantity, unit=parsed.unit, tags=data.tags
        )
    except ValidationError as exc:
        raise InvalidInputError(details=[ErrorDetail(loc=["text"], message=str(exc))]) from exc
    results = await add_items(
        AddItems(shopping_list_id=data.shopping_list_id, items=[incoming]), source
    )
    return QuickAddResult(
        parsed=ParsedItem(name=parsed.name, quantity=parsed.quantity, unit=parsed.unit),
        result=results[0],
    )


async def update_item(id: UUID, data: ItemUpdate, source: Source) -> ItemRead:
    item = await _item_for_update(id)
    if "unit" in data.model_fields_set:
        quantity = data.quantity if "quantity" in data.model_fields_set else item.quantity
        quantity, unit = normalize_quantity(quantity, data.unit)
        data = data.model_copy(update={"quantity": quantity, "unit": unit})
    await item_repo.update(item, data)
    if "tags" in data.model_fields_set:
        item.tags = await _resolve_tags(item.shopping_list_id, data.tags or [])
        await get_current_session().flush()
    result = ItemRead.model_validate(item)
    await record_event(
        item.shopping_list_id, EventType.ITEM_UPDATED, source, EventPayload(items=[result])
    )
    return result


async def _selected_items(shopping_list_id: UUID, ids: Sequence[UUID]) -> list[Item]:
    items = await item_repo.get_by_ids(ids)
    if len(items) != len(set(ids)) or any(
        item.shopping_list_id != shopping_list_id for item in items
    ):
        raise ItemNotFoundError()
    by_id = {item.id: item for item in items}
    return [by_id[id] for id in dict.fromkeys(ids)]


async def set_bought(
    shopping_list_id: UUID, ids: Sequence[UUID], bought: bool, source: Source
) -> list[ItemRead]:
    await ensure_shopping_list_access(shopping_list_id, lock=True)
    items = await _selected_items(shopping_list_id, ids)
    return await _set_bought(shopping_list_id, items, bought, source)


async def _set_bought(
    shopping_list_id: UUID, items: Sequence[Item], bought: bool, source: Source
) -> list[ItemRead]:
    now = datetime.now(UTC)
    for item in items:
        if item.is_bought != bought:
            item.is_bought = bought
            item.bought_at = now if bought else None
    await get_current_session().flush()
    result = [ItemRead.model_validate(item) for item in items]
    await record_event(
        shopping_list_id,
        EventType.ITEMS_BOUGHT if bought else EventType.ITEMS_UNBOUGHT,
        source,
        EventPayload(items=result),
    )
    return result


async def _delete_items(
    shopping_list_id: UUID,
    items: Sequence[Item],
    source: Source,
    type: EventType = EventType.ITEMS_DELETED,
) -> int:
    snapshots = [ItemRead.model_validate(item) for item in items]
    await item_repo.delete_by_ids([item.id for item in items])
    await record_event(shopping_list_id, type, source, EventPayload(items=snapshots))
    return len(items)


async def remove_items(
    shopping_list_id: UUID,
    source: Source,
    *,
    ids: Sequence[UUID] | None = None,
    tag: str | None = None,
) -> int:
    await ensure_shopping_list_access(shopping_list_id, lock=True)
    if (ids is None) == (tag is None):
        raise InvalidInputError("Укажите либо ids, либо tag")
    if ids is not None:
        items = await _selected_items(shopping_list_id, ids)
    else:
        normalized = normalize_name(tag or "")
        items = [
            item
            for item in await item_repo.for_shopping_list(shopping_list_id, include_bought=True)
            if any(t.name_normalized == normalized for t in item.tags)
        ]
    return await _delete_items(shopping_list_id, items, source)


async def delete_item(id: UUID, source: Source) -> None:
    item = await _item_for_update(id)
    await _delete_items(item.shopping_list_id, [item], source)


async def clear_bought(shopping_list_id: UUID, source: Source) -> int:
    await ensure_shopping_list_access(shopping_list_id, lock=True)
    items = [
        item
        for item in await item_repo.for_shopping_list(shopping_list_id, include_bought=True)
        if item.is_bought
    ]
    return await _delete_items(shopping_list_id, items, source, EventType.BOUGHT_CLEARED)


async def list_tags(shopping_list_id: UUID) -> list[TagUsageRead]:
    await ensure_shopping_list_access(shopping_list_id)
    return [
        TagUsageRead(id=usage.tag.id, name=usage.tag.name, open_count=usage.open_count)
        for usage in await tag_repo.usage(shopping_list_id)
    ]


async def rename_tag(id: UUID, name: str, source: Source) -> TagRead:
    tag = await _tag_for_update(id)
    try:
        data = TagUpdate(name=name)
    except ValidationError as exc:
        raise InvalidInputError(details=[ErrorDetail(loc=["name"], message=str(exc))]) from exc
    previous = TagRead.model_validate(tag)
    existing = await tag_repo.by_name(tag.shopping_list_id, data.name_normalized)
    if existing is not None and existing.id != tag.id:
        for item in await item_repo.for_shopping_list(tag.shopping_list_id, include_bought=True):
            if any(t.id == tag.id for t in item.tags):
                remaining = [t for t in item.tags if t.id != tag.id]
                item.tags = remaining if existing in remaining else [*remaining, existing]
        await get_current_session().flush()
        await tag_repo.delete(tag)
        result = TagRead.model_validate(existing)
        type = EventType.TAGS_MERGED
    else:
        await tag_repo.update(tag, data)
        result = TagRead.model_validate(tag)
        type = EventType.TAG_RENAMED
    await record_event(
        tag.shopping_list_id, type, source, EventPayload(tag=result, previous_tag=previous)
    )
    return result


async def delete_tag(id: UUID, source: Source) -> None:
    tag = await _tag_for_update(id)
    snapshot = TagRead.model_validate(tag)
    for item in await item_repo.for_shopping_list(tag.shopping_list_id, include_bought=True):
        item.tags = [t for t in item.tags if t.id != tag.id]
    await get_current_session().flush()
    await tag_repo.delete(tag)
    await record_event(
        tag.shopping_list_id, EventType.TAG_DELETED, source, EventPayload(tag=snapshot)
    )


async def bulk_tag(id: UUID, action: Literal["mark_bought", "delete_items"], source: Source) -> int:
    tag = await _tag_for_update(id)
    items = [
        item
        for item in await item_repo.for_shopping_list(tag.shopping_list_id, include_bought=True)
        if any(t.id == tag.id for t in item.tags)
    ]
    if action == "mark_bought":
        await _set_bought(tag.shopping_list_id, items, True, source)
        return len(items)
    if action == "delete_items":
        return await _delete_items(tag.shopping_list_id, items, source)
    raise InvalidInputError("Неизвестное массовое действие")
