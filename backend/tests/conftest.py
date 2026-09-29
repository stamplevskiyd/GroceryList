"""Общие фикстуры тестов (ADR-0011)."""

import os
from collections.abc import Iterator

import pytest

from grocery.config import get_settings


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
