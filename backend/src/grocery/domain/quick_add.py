"""Разбор строки; схемы здесь не импортируются — domain остаётся нижним слоем."""

import re
from dataclasses import dataclass
from decimal import Decimal

from grocery.domain.normalization import clean_name, normalize_quantity

_PATTERN = re.compile(r"^(.+?)\s+(\d+(?:[.,]\d+)?)\s*([^\W\d_]+\.?)?$", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ParsedItem:
    name: str
    quantity: Decimal | None = None
    unit: str | None = None


def parse_quick_add(text: str) -> ParsedItem:
    text = clean_name(text)
    match = _PATTERN.fullmatch(text)
    if match:
        name, number, unit = match.groups()
        quantity, unit = normalize_quantity(Decimal(number.replace(",", ".")), unit)
    else:
        name, quantity, unit = text, None, None
    return ParsedItem(name=name[:1].upper() + name[1:], quantity=quantity, unit=unit)
