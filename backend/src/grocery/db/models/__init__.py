"""Все ORM-модели. Импорт пакета регистрирует их в Base.metadata (нужно Alembic)."""

from grocery.db.models.user import User

__all__ = ["User"]
