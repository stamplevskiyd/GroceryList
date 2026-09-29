"""Общие фикстуры тестов (ADR-0011)."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from testcontainers.community.postgres import PostgresContainer

from grocery.config import get_settings
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
