"""Пользователь (спец. §4)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from grocery.db.base import Entity


class User(Entity):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
