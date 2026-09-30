from decimal import Decimal

import pytest

from grocery.db.models import Item
from grocery.schemas.items import ItemCreate
from grocery.schemas.sources import AppAttribution, AppSource, McpAttribution, McpSource
from grocery.services.shopping_list_service.merge import merge_item


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [(None, None, None), (None, "2", "2"), ("2", None, "2"), ("2", "3", "5")],
)
def test_nullable_quantity_merge(
    existing: str | None, incoming: str | None, expected: str | None
) -> None:
    item = Item(
        quantity=Decimal(existing) if existing else None, note=None, sources=[AppAttribution()]
    )
    patch = merge_item(
        item,
        ItemCreate(name="Лук", quantity=Decimal(incoming) if incoming else None),
        AppSource(device_id="phone"),
    )
    assert patch.quantity == (Decimal(expected) if expected else None)
    assert patch.sources == [AppAttribution()]


def test_merge_notes_and_sources_without_transport_identifiers() -> None:
    item = Item(quantity=None, note="красный", sources=[AppAttribution()])
    patch = merge_item(
        item,
        ItemCreate(name="Лук", note="крупный"),
        McpSource(client_id="secret", client_name="Claude"),
    )
    assert patch.note == "красный; крупный"
    assert patch.sources == [AppAttribution(), McpAttribution(client_name="Claude")]
    item.note, item.sources = patch.note, patch.sources
    again = merge_item(
        item,
        ItemCreate(name="Лук", note="крупный"),
        McpSource(client_id="another", client_name="Claude"),
    )
    assert again.note == "красный; крупный"
    assert again.sources == patch.sources


def test_identical_compound_note_does_not_duplicate() -> None:
    item = Item(quantity=None, note="красный; крупный", sources=[AppAttribution()])
    patch = merge_item(
        item, ItemCreate(name="Лук", note="красный; крупный"), AppSource(device_id="phone")
    )
    assert patch.note == "красный; крупный"
