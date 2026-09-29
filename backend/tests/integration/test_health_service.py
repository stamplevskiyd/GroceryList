"""Проверка БД для /api/health не зависает на недоступном хосте (ADR-0015)."""

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from grocery.db.session import override_session_factory
from grocery.services.health import database_is_available


async def test_hanging_connection_is_reported_as_unavailable() -> None:
    async def never_connects() -> Any:
        # Как сетевая «чёрная дыра»: соединение не устанавливается и не отклоняется.
        await asyncio.sleep(3600)

    hanging = create_async_engine("postgresql+asyncpg://", async_creator=never_connects)
    try:
        with override_session_factory(async_sessionmaker(hanging)):
            async with asyncio.timeout(5):
                available = await database_is_available(max_seconds=0.2)
    finally:
        await hanging.dispose()

    assert available is False
