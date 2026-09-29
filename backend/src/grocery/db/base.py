"""Базовые классы ORM-моделей (ADR-0013)."""

from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Стабильные имена ограничений — чтобы Alembic мог их удалять и переименовывать.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Entity(Base):
    """Таблица-сущность: ключ UUIDv7 и метки времени. Таблицы связей наследуют Base."""

    __abstract__ = True
    # Значения server_default / onupdate сразу забираются через RETURNING: иначе чтение
    # created_at / updated_at после flush вызвало бы неявный запрос, запрещённый в async.
    # ClassVar здесь нельзя: SQLAlchemy типизирует __mapper_args__ как атрибут экземпляра.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
