"""Чистое объединение; сохраняет имя и порядок первой позиции (§5.3)."""

from grocery.db.models import Item
from grocery.schemas.items import ItemCreate, ItemUpdate
from grocery.schemas.sources import ItemSource, Source, item_source


class MergeUpdate(ItemUpdate):
    sources: list[ItemSource]


def merge_item(existing: Item, incoming: ItemCreate, source: Source) -> MergeUpdate:
    quantity = existing.quantity
    if incoming.quantity is not None:
        quantity = incoming.quantity if quantity is None else quantity + incoming.quantity
    note = existing.note
    if incoming.note and incoming.note != note and incoming.note not in (note or "").split("; "):
        note = f"{note}; {incoming.note}" if note else incoming.note
    attribution = item_source(source)
    sources = list(existing.sources)
    if attribution not in sources:
        sources.append(attribution)
    return MergeUpdate(quantity=quantity, note=note, sources=sources)
