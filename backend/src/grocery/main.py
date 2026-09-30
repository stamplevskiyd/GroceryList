"""Сборка приложения: create_app() и lifespan (ADR-0014).

Запуск: uvicorn grocery.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grocery.api.errors import register_error_handlers
from grocery.api.routers import health
from grocery.config import get_settings
from grocery.db.session import configure_engine, dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Неполная конфигурация роняет приложение здесь, при старте (ADR-0006).
    settings = get_settings()
    configure_engine(str(settings.db.url))
    try:
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="GroceryList", version=get_settings().app.version, lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    return app
