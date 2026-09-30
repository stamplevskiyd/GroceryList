from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

Quantity = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]
PositiveQuantity = Annotated[Quantity, Field(gt=0, allow_inf_nan=False)]


class CountRead(BaseModel):
    count: int = Field(ge=0)
