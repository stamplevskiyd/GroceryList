"""Схемы сессий и публичной информации пользователя."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


class LoginCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, AfterValidator(str.strip), Field(min_length=1, max_length=64)]
    password: str = Field(min_length=1, repr=False)


class RegistrationCreate(LoginCreate):
    password: str = Field(min_length=8, max_length=128, repr=False)

    @field_validator("password")
    @classmethod
    def nonblank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Пароль не может состоять только из пробелов")
        return value


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


class LoginResult(BaseModel):
    session: SessionIssued
    me: MeRead
