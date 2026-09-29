"""GET /api/health — проверка для деплоя и healthcheck (ADR-0015)."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from grocery.config import get_settings
from grocery.db.session import override_session_factory


async def test_health_ok_reports_version(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_VERSION", "v1.2.3")
    get_settings.cache_clear()  # фикстура app уже прочитала настройки

    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "v1.2.3"}


async def test_health_is_public(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200


async def test_health_when_database_is_down_returns_503(client: httpx.AsyncClient) -> None:
    # Порт 1 на localhost закрыт — соединение отклоняется сразу.
    broken = create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/db")
    try:
        with override_session_factory(async_sessionmaker(broken)):
            response = await client.get("/api/health")
    finally:
        await broken.dispose()

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
