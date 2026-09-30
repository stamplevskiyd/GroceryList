"""Test-only API probes shared by unit-of-work and error contract tests."""

from fastapi import APIRouter, FastAPI
from sqlalchemy import func, select

from grocery.api.deps import DbUnitOfWork
from grocery.db.models import User
from grocery.db.session import get_current_session


def add_unit_of_work_probe_routes(app: FastAPI) -> None:
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
