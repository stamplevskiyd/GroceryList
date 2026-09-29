"""Сессия БД на единицу работы, хранится в ContextVar (ADR-0004).

Единственное место, где создаются сессии и делается commit. Единицу работы открывают:
dependency REST, middleware MCP, push-воркер.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

type AfterCommitHook = Callable[[], Awaitable[None]]

_session: ContextVar[AsyncSession | None] = ContextVar("db_session", default=None)
_after_commit: ContextVar[list[AfterCommitHook] | None] = ContextVar(
    "db_after_commit", default=None
)


class _Database:
    engine: AsyncEngine | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None


_database = _Database()


def configure_engine(url: str) -> AsyncEngine:
    """Создать движок и фабрику сессий. Вызывается один раз в lifespan приложения."""
    engine = create_async_engine(url, pool_pre_ping=True)
    _database.engine = engine
    _database.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine


async def dispose_engine() -> None:
    if _database.engine is not None:
        await _database.engine.dispose()
    _database.engine = None
    _database.session_factory = None


@contextmanager
def override_session_factory(factory: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    """Подменить фабрику сессий — только для тестов (ADR-0011)."""
    previous = _database.session_factory
    _database.session_factory = factory
    try:
        yield
    finally:
        _database.session_factory = previous


def _session_factory() -> async_sessionmaker[AsyncSession]:
    if _database.session_factory is None:
        raise RuntimeError("БД не настроена: configure_engine() не вызывался")
    return _database.session_factory


@asynccontextmanager
async def unit_of_work() -> AsyncIterator[AsyncSession]:
    """Открыть сессию в контексте; закоммитить при успехе, откатить при исключении.

    Хуки on_commit выполняются после коммита, вне транзакции. Упавший хук логируется и не
    превращает уже сохранённое изменение в ошибку.
    """
    if _session.get() is not None:
        raise RuntimeError("unit_of_work уже открыт в этом контексте")
    hooks: list[AfterCommitHook] = []
    async with _session_factory()() as session:
        session_token = _session.set(session)
        hooks_token = _after_commit.set(hooks)
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            _session.reset(session_token)
            _after_commit.reset(hooks_token)
    for hook in hooks:
        try:
            await hook()
        except Exception:
            logger.exception("Хук после коммита завершился ошибкой; данные уже сохранены")


def get_current_session() -> AsyncSession:
    session = _session.get()
    if session is None:
        raise RuntimeError("Сессия БД не открыта: вызов вне unit_of_work")
    return session


def on_commit(hook: AfterCommitHook) -> None:
    """Выполнить hook после успешного коммита текущей единицы работы."""
    hooks = _after_commit.get()
    if hooks is None:
        raise RuntimeError("on_commit вызван вне unit_of_work")
    hooks.append(hook)
