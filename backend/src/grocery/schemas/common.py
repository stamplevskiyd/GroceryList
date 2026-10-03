from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, PlainSerializer

from grocery.domain.normalization import clean_name, normalize_name

Quantity = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]
PositiveQuantity = Annotated[Quantity, Field(gt=0, allow_inf_nan=False)]


class CountRead(BaseModel):
    count: int = Field(ge=0)


def _normalized_name_fits(value: str) -> str:
    if len(normalize_name(value)) > 255:
        raise ValueError("Нормализованное название должно содержать не более 255 символов")
    return value


def _normalized_unit_fits(value: str) -> str:
    if len(normalize_name(value).rstrip(".")) > 64:
        raise ValueError("Нормализованная единица должна содержать не более 64 символов")
    return value


Name = Annotated[
    str,
    AfterValidator(clean_name),
    Field(min_length=1, max_length=255),
    AfterValidator(_normalized_name_fits),
]
Unit = Annotated[str, Field(max_length=64), AfterValidator(_normalized_unit_fits)]
