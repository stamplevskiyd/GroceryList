from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from grocery.domain.enums import AddStatus
from grocery.domain.normalization import clean_name, normalize_name, normalize_quantity
from grocery.schemas.sources import ItemSource

Name = Annotated[str, AfterValidator(clean_name), Field(min_length=1, max_length=255)]
Quantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    quantity: Quantity | None = None
    unit: str | None = Field(default=None, max_length=64)
    tags: list[Name] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def normalize_units(self) -> ItemCreate:
        self.quantity, self.unit = normalize_quantity(self.quantity, self.unit)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name_normalized(self) -> str:
        return normalize_name(self.name)


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    quantity: Quantity | None = None
    unit: str | None = Field(default=None, max_length=64)
    tags: list[Name] | None = None
    note: str | None = None

    @field_validator("name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Название не может быть пустым")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str] | None) -> list[str]:
        if value is None:
            raise ValueError("Теги должны быть списком; для удаления передайте []")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name_normalized(self) -> str | None:
        return None if self.name is None else normalize_name(self.name)


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    shopping_list_id: UUID
    name: str
    quantity: Decimal | None
    unit: str | None
    note: str | None
    tags: list[TagRead]
    sources: list[ItemSource]
    is_bought: bool
    bought_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AddItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shopping_list_id: UUID
    items: list[ItemCreate] = Field(min_length=1)


class AddItemResult(BaseModel):
    status: AddStatus
    item: ItemRead


class ParsedItem(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit: str | None = None


class QuickAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shopping_list_id: UUID
    text: str = Field(min_length=1)
    tags: list[Name] = Field(default_factory=list)


class QuickAddResult(BaseModel):
    parsed: ParsedItem
    result: AddItemResult
