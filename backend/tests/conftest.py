"""Общие фикстуры тестов (ADR-0011)."""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from grocery.config import get_settings
from grocery.db import models  # noqa: F401 — все таблицы в Base.metadata для TRUNCATE
from grocery.db.base import Base
from grocery.db.session import override_session_factory
from tests.support import POSTGRES_IMAGE, alembic_config


def pytest_configure(config: pytest.Config) -> None:
    # Минимальное окружение для Settings. Настоящая БД тестам не нужна: фабрика сессий
    # подменяется фикстурами, поэтому DB_URL указывает на заведомо закрытый порт.
    os.environ.setdefault("APP_PUBLIC_URL", "http://testserver")
    os.environ.setdefault("DB_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    """URL основной тестовой базы; схема создаётся миграциями, а не create_all (ADR-0011)."""
    url = postgres.get_connection_url()
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


async def _truncate_all(engine: AsyncEngine) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        # Имена таблиц берутся из metadata, а не из ввода.
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db(engine: AsyncEngine, request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Изоляция теста (ADR-0011).

    По умолчанию — внешняя транзакция: commit() в unit_of_work фиксирует только savepoint,
    после теста всё откатывается. С маркером real_commits — обычные коммиты и TRUNCATE после.
    """
    if request.node.get_closest_marker("real_commits"):
        with override_session_factory(async_sessionmaker(engine, expire_on_commit=False)):
            yield
        await _truncate_all(engine)
        return

    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        with override_session_factory(factory):
            yield
        await transaction.rollback()
