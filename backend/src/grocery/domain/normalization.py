"""Чистые правила названий и единиц (спец. §5.1–5.2)."""

from decimal import Decimal

_UNITS: dict[str, tuple[str, int]] = {
    "г": ("г", 1),
    "гр": ("г", 1),
    "кг": ("г", 1000),
    "мл": ("мл", 1),
    "л": ("мл", 1000),
    "шт": ("шт", 1),
    "штук": ("шт", 1),
    "штуки": ("шт", 1),
    "уп": ("уп", 1),
    "упаковка": ("уп", 1),
    "пачка": ("уп", 1),
}


def clean_name(value: str) -> str:
    return " ".join(value.split())


def normalize_name(value: str) -> str:
    return clean_name(value).lower().replace("ё", "е")


def normalize_quantity(
    quantity: Decimal | None, unit: str | None
) -> tuple[Decimal | None, str | None]:
    if unit is None or not unit.strip():
        return quantity, None
    unit = normalize_name(unit).rstrip(".")
    base, factor = _UNITS.get(unit, (unit, 1))
    return (quantity * factor if quantity is not None else None), base
