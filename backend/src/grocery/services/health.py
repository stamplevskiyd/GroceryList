"""Проверка доступности БД для /api/health (ADR-0015)."""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from grocery.db.session import unit_of_work

logger = logging.getLogger(__name__)

# Недоступный хост без ответа (пауза контейнера, сетевой разрыв) иначе держит запрос до
# таймаута asyncpg в 60 секунд — healthcheck и деплой зависли бы вместо быстрого 503.
DATABASE_CHECK_TIMEOUT = 3.0


async def database_is_available(max_seconds: float = DATABASE_CHECK_TIMEOUT) -> bool:
    """SELECT 1 в собственной единице работы, не дольше max_seconds секунд.

    Превышение времени — часть результата («недоступна» → 503), а не исключение, поэтому
    ограничение внутри функции, а не asyncio.timeout у вызывающего.

    Исключение из правила «единицу работы открывает адаптер»: недоступная БД должна давать
    503, а не 500 из общей dependency.
    """
    try:
        async with asyncio.timeout(max_seconds), unit_of_work() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError, OSError, TimeoutError:
        logger.warning("База данных недоступна", exc_info=True)
        return False
    return True
