"""Единая сериализация типизированного JSONB (ADR-0013)."""

from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class PydanticJSON[T](TypeDecorator[T]):
    impl = JSONB
    cache_ok = True

    def __init__(self, schema: Any) -> None:
        super().__init__()
        self.schema = schema
        self.adapter: TypeAdapter[T] = TypeAdapter(schema)

    def process_bind_param(self, value: T | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        validated = self.adapter.validate_python(value)
        return self.adapter.dump_python(validated, mode="json")

    def process_result_value(self, value: Any, dialect: Dialect) -> T | None:
        return None if value is None else self.adapter.validate_python(value)
