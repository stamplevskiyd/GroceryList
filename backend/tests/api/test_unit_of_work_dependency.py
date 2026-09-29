"""DbUnitOfWork: сессия видна в обработчике, коммит — до ответа (ADR-0004)."""

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy import func, select

from grocery.api.deps import DbUnitOfWork
from grocery.db.models import User
from grocery.db.session import get_current_session, unit_of_work


def _add_probe_routes(app: FastAPI) -> None:
    router = APIRouter(dependencies=[DbUnitOfWork])

    @router.get("/probe/users/count")
    async def count_users() -> dict[str, int]:
        session = get_current_session()
        return {"count": await session.scalar(select(func.count()).select_from(User)) or 0}

    @router.post("/probe/users/{username}")
    async def add_user_without_flush(username: str) -> dict[str, str]:
        # Без flush: ошибка уникальности возникнет только при коммите в dependency.
        get_current_session().add(User(username=username, password_hash="h"))
        return {"status": "accepted"}

    app.include_router(router)


async def test_handler_sees_session_and_changes_are_committed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    _add_probe_routes(app)

    assert (await client.post("/probe/users/anna")).status_code == 200
    response = await client.get("/probe/users/count")

    assert response.json() == {"count": 1}


@pytest.mark.real_commits
async def test_commit_failure_is_reported_as_500(app: FastAPI) -> None:
    # В savepoint-режиме уникальность проверяется так же, но здесь важен настоящий COMMIT:
    # dependency со scope="function" должна завершить его до отправки ответа.
    _add_probe_routes(app)
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/probe/users/anna")

    assert response.status_code == 500
