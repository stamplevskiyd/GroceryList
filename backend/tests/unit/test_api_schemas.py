from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from grocery.domain.enums import AddStatus
from grocery.schemas.events import EventPayload
from grocery.schemas.items import AddItemResult, ItemCreate, ItemRead, ItemUpdate, ParsedItem


@pytest.fixture
def item() -> ItemRead:
    now = datetime.now(UTC)
    return ItemRead(
        id=uuid7(),
        shopping_list_id=uuid7(),
        name="Лук",
        quantity=Decimal("0.1234567890123456789012345678"),
        unit="г",
        note=None,
        tags=[],
        sources=[],
        is_bought=False,
        bought_at=None,
        created_at=now,
        updated_at=now,
    )


def test_quantity_is_json_number() -> None:
    parsed = ParsedItem(name="Лук", quantity=Decimal("1500"), unit="г")
    assert parsed.quantity == Decimal("1500")
    assert isinstance(parsed.model_dump(mode="json")["quantity"], float)
    assert parsed.model_dump(mode="json")["quantity"] == 1500.0


@pytest.mark.parametrize("quantity", [Decimal("0.1234567890123456789012345678"), None])
def test_nested_quantity_serialization(item: ItemRead, quantity: Decimal | None) -> None:
    item.quantity = quantity
    parsed = ParsedItem(name=item.name, quantity=quantity, unit=item.unit)
    result = AddItemResult(status=AddStatus.CREATED, item=item)
    payload = EventPayload(items=[item], results=[result])
    assert item.quantity == quantity
    assert parsed.quantity == quantity
    assert item.model_dump()["quantity"] == quantity
    assert result.item.quantity == quantity
    assert payload.items[0].quantity == quantity
    expected = float(quantity) if quantity is not None else None
    assert item.model_dump(mode="json")["quantity"] == expected
    assert parsed.model_dump(mode="json")["quantity"] == expected
    assert result.model_dump(mode="json")["item"]["quantity"] == expected
    assert payload.model_dump(mode="json")["items"][0]["quantity"] == expected
    assert payload.model_dump(mode="json")["results"][0]["item"]["quantity"] == expected


@pytest.mark.parametrize("schema", [ItemCreate, ItemUpdate])
def test_input_quantity_preserves_decimal_and_serializes_as_number(
    schema: type[ItemCreate] | type[ItemUpdate],
) -> None:
    quantity = Decimal("0.1234567890123456789012345678")
    item = schema(name="Лук", quantity=quantity)
    assert item.quantity == quantity
    assert item.model_dump(mode="json")["quantity"] == float(quantity)


@pytest.mark.parametrize("schema", [ItemCreate, ItemUpdate])
@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "-Infinity"])
def test_input_quantity_rejects_nonpositive_or_nonfinite_values(
    schema: type[ItemCreate] | type[ItemUpdate], quantity: str
) -> None:
    with pytest.raises(ValidationError):
        schema(name="Лук", quantity=Decimal(quantity))


def test_quantity_serialization_schema_is_number() -> None:
    schema = ParsedItem.model_json_schema(mode="serialization")
    assert schema["properties"]["quantity"]["anyOf"] == [{"type": "number"}, {"type": "null"}]


def test_count_read_rejects_negative_counts() -> None:
    from grocery.schemas.common import CountRead

    assert CountRead(count=0).model_dump(mode="json") == {"count": 0}
    with pytest.raises(ValidationError):
        CountRead(count=-1)
