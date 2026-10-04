from decimal import Decimal

import pytest
from pydantic import ValidationError

from grocery.domain.normalization import normalize_name, normalize_quantity
from grocery.domain.quick_add import parse_quick_add
from grocery.schemas.items import ItemCreate, ItemUpdate
from grocery.schemas.tags import TagUpdate


def test_name_normalization() -> None:
    assert normalize_name("  Зелёный  ЛУК \t") == "зеленый лук"


@pytest.mark.parametrize(
    ("text", "name", "quantity", "unit"),
    [
        ("молоко 2 л", "Молоко", "2000", "мл"),
        ("яблоки 1,5 кг", "Яблоки", "1500", "г"),
        ("яйца 10", "Яйца", "10", None),
        ("батарейки АА 4 шт.", "Батарейки АА", "4", "шт"),
        ("соль", "Соль", None, None),
        ("хлеб 1 буханка", "Хлеб", "1", "буханка"),
        ("молоко 2л", "Молоко", "2000", "мл"),
        ("чай Earl Grey", "Чай Earl Grey", None, None),
        ("вода 2 л газ", "Вода 2 л газ", None, None),
        ("витамин B12", "Витамин B12", None, None),
    ],
)
def test_quick_add_examples(text: str, name: str, quantity: str | None, unit: str | None) -> None:
    parsed = parse_quick_add(text)
    assert parsed.name == name
    assert parsed.quantity == (Decimal(quantity) if quantity is not None else None)
    assert parsed.unit == unit


@pytest.mark.parametrize(
    ("unit", "expected", "factor"),
    [
        ("КГ", "г", 1000),
        ("гр.", "г", 1),
        ("штуки", "шт", 1),
        ("пачка", "уп", 1),
        ("  БУХАНКА  ", "буханка", 1),
        (None, None, 1),
    ],
)
def test_unit_conversion(unit: str | None, expected: str | None, factor: int) -> None:
    assert normalize_quantity(Decimal("1.5"), unit) == (Decimal("1.5") * factor, expected)
    assert normalize_quantity(None, unit) == (None, expected)


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_empty_names_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        ItemCreate(name=name)


def test_create_normalizes_without_changing_display_name() -> None:
    item = ItemCreate(name="  Зелёный  ЛУК ", quantity=Decimal("1.5"), unit="кг")
    assert item.name == "Зелёный ЛУК"
    assert item.name_normalized == "зеленый лук"
    assert (item.quantity, item.unit) == (Decimal("1500"), "г")


def test_patch_omitted_fields_and_explicit_null_remain_distinct() -> None:
    assert ItemUpdate(note=None).model_fields_set == {"note"}
    assert ItemUpdate().name_normalized is None
    assert ItemUpdate(name="Зелёный ЛУК").name_normalized == "зеленый лук"
    with pytest.raises(ValidationError):
        ItemUpdate(name=None)


@pytest.mark.parametrize("name", [123, None, [], {}])
def test_malformed_names_return_validation_errors(name: object) -> None:
    for schema in (ItemCreate, ItemUpdate, TagUpdate):
        with pytest.raises(ValidationError):
            schema.model_validate({"name": name})


@pytest.mark.parametrize("tags", [[123], "Суп", [None], ["   "]])
def test_malformed_tags_return_validation_errors(tags: object) -> None:
    with pytest.raises(ValidationError):
        ItemCreate.model_validate({"name": "Лук", "tags": tags})
