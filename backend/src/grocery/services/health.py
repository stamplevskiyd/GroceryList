"""Проверка доступности БД для /api/health (ADR-0015)."""

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from grocery.db.session import unit_of_work

logger = logging.getLogger(__name__)


async def database_is_available() -> bool:
    """SELECT 1 в собственной единице работы.

    Исключение из правила «единицу работы открывает адаптер»: недоступная БД должна давать
    503, а не 500 из общей dependency.
    """
    try:
        async with unit_of_work() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError, OSError:
        logger.warning("База данных недоступна", exc_info=True)
        return False
    return True
