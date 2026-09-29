"""Схемы пользователя для репозитория. Регистрации через API нет (спец. §6.1)."""

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password_hash: str


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password_hash: str | None = None
