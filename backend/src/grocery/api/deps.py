"""Общие dependency REST-адаптера."""

from collections.abc import AsyncIterator

from fastapi import Depends

from grocery.db.session import unit_of_work


async def _db_unit_of_work() -> AsyncIterator[None]:
    async with unit_of_work():
        yield


# scope="function": коммит завершается до отправки ответа — упавший коммит даёт 500,
# а не «200 OK» с потерянными данными (ADR-0004).
DbUnitOfWork = Depends(_db_unit_of_work, scope="function")
