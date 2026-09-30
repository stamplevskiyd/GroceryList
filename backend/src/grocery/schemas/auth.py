"""Схемы сессий и публичной информации пользователя."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    user_id: UUID
    token_hash: str
    expires_at: datetime
    device_id: str


class SessionIssued(BaseModel):
    token: str = Field(repr=False)
    expires_at: datetime


class ShoppingListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class MeRead(BaseModel):
    id: UUID
    username: str
    shopping_lists: list[ShoppingListRead]
