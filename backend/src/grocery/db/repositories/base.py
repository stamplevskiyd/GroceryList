"""Базовый репозиторий: стандартный набор методов для всех моделей (ADR-0005).

Сессия берётся из контекста (ADR-0004); репозитории не коммитят.
"""

from collections.abc import Sequence
from typing import Any, ClassVar, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CursorResult, delete, select

from grocery.db.base import Entity
from grocery.db.session import get_current_session


def _values(data: BaseModel, *, exclude: frozenset[str], only_set: bool) -> dict[str, Any]:
    """Поля схемы для записи в модель.

    Вложенные Pydantic-объекты остаются объектами (их сериализует тип колонки), вычисляемые
    поля (computed_field) включаются — через них схемы передают нормализованные значения.
    При частичном обновлении (only_set) вычисляемое поле пишется, только если оно не None:
    в схемах обновления None означает «исходное поле не передано».
    """
    schema = type(data)
    if not only_set:
        names = (set(schema.model_fields) | set(schema.model_computed_fields)) - exclude
        return {name: getattr(data, name) for name in names}
    values = {name: getattr(data, name) for name in data.model_fields_set - exclude}
    for name in set(schema.model_computed_fields) - exclude:
        value = getattr(data, name)
        if value is not None:
            values[name] = value
    return values


class Repository[M: Entity, C: BaseModel, U: BaseModel]:
    # Поля схем, которые не пишутся в модель напрямую (например, связи).
    exclude_on_write: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, model: type[M]) -> None:
        self.model = model

    async def get(self, id: UUID) -> M | None:
        return await get_current_session().get(self.model, id)

    async def get_by_ids(self, ids: Sequence[UUID]) -> list[M]:
        if not ids:
            return []
        result = await get_current_session().scalars(
            select(self.model).where(self.model.id.in_(ids))
        )
        return list(result)

    async def add(self, data: C, **extra: Any) -> M:
        obj = self._build(data, extra)
        session = get_current_session()
        session.add(obj)
        await session.flush()
        return obj

    async def add_all(self, items: Sequence[C], **extra: Any) -> list[M]:
        objs = [self._build(data, extra) for data in items]
        session = get_current_session()
        session.add_all(objs)
        await session.flush()
        return objs

    async def update(self, obj: M, data: U) -> M:
        for field, value in _values(data, exclude=self.exclude_on_write, only_set=True).items():
            setattr(obj, field, value)
        await get_current_session().flush()
        return obj

    async def delete(self, obj: M) -> None:
        session = get_current_session()
        await session.delete(obj)
        await session.flush()

    async def delete_by_ids(self, ids: Sequence[UUID]) -> int:
        if not ids:
            return 0
        # execute() типизирован как Result; для DELETE это CursorResult с rowcount.
        result = cast(
            CursorResult[Any],
            await get_current_session().execute(delete(self.model).where(self.model.id.in_(ids))),
        )
        return result.rowcount

    def _build(self, data: C, extra: dict[str, Any]) -> M:
        values = _values(data, exclude=self.exclude_on_write, only_set=False)
        return self.model(**values, **extra)
