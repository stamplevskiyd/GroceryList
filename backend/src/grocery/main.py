"""Сборка приложения: create_app() и lifespan (ADR-0014).

Запуск: uvicorn grocery.main:create_app --factory
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grocery.api.errors import register_error_handlers
from grocery.api.routers import auth as auth_router
from grocery.api.routers import events, health, items, me, oauth, tags, tokens
from grocery.config import get_settings
from grocery.db.session import configure_engine, dispose_engine
from grocery.mcp_server.server import create_mcp
from grocery.services import auth


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Неполная конфигурация роняет приложение здесь, при старте (ADR-0006).
    settings = get_settings()
    logging.basicConfig(level=settings.app.log_level)
    logging.getLogger().setLevel(settings.app.log_level)
    configure_engine(str(settings.db.url))
    try:
        await auth.initialize_passwords()
        async with app.state.mcp.session_manager.run():
            yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="GroceryList", version=get_settings().app.version, lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(auth_router.protected_router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(items.router, prefix="/api")
    app.include_router(tags.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(tokens.router, prefix="/api")
    app.include_router(oauth.router)
    app.include_router(oauth.protected_router, prefix="/api")
    server, mcp_app = create_mcp(get_settings().app)
    app.state.mcp = server
    app.mount("/", mcp_app)
    return app
