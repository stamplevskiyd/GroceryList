"""DbUnitOfWork: сессия видна в обработчике, коммит — до ответа (ADR-0004)."""

import httpx
import pytest
from fastapi import FastAPI

from grocery.db.models import User
from grocery.db.session import unit_of_work
from tests.support_api import add_unit_of_work_probe_routes


async def test_handler_sees_session_and_changes_are_committed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    add_unit_of_work_probe_routes(app)

    assert (await client.post("/probe/users/anna")).status_code == 200
    response = await client.get("/probe/users/count")

    assert response.json() == {"count": 1}


@pytest.mark.real_commits
async def test_commit_failure_is_reported_as_500(app: FastAPI) -> None:
    # В savepoint-режиме уникальность проверяется так же, но здесь важен настоящий COMMIT:
    # dependency со scope="function" должна завершить его до отправки ответа.
    add_unit_of_work_probe_routes(app)
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/probe/users/anna")

    assert response.status_code == 500
