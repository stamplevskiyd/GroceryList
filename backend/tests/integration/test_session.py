"""unit_of_work: коммит, откат, контекст (ADR-0004)."""

import pytest
from sqlalchemy import func, select

from grocery.db.models import User
from grocery.db.session import get_current_session, unit_of_work


async def _count_users() -> int:
    async with unit_of_work() as session:
        return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_commits_on_success() -> None:
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))

    assert await _count_users() == 1


async def _add_user_then_fail() -> None:
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))
        await session.flush()
        raise ValueError("boom")


async def test_rolls_back_on_exception() -> None:
    with pytest.raises(ValueError, match="boom"):
        await _add_user_then_fail()

    assert await _count_users() == 0


async def test_current_session_is_the_unit_of_work_session() -> None:
    async with unit_of_work() as session:
        assert get_current_session() is session


async def test_current_session_outside_unit_of_work_raises() -> None:
    with pytest.raises(RuntimeError, match="unit_of_work"):
        get_current_session()


async def test_context_is_reset_after_exit() -> None:
    async with unit_of_work():
        pass

    with pytest.raises(RuntimeError, match="unit_of_work"):
        get_current_session()


async def test_nested_unit_of_work_raises() -> None:
    async with unit_of_work():
        with pytest.raises(RuntimeError, match="уже открыт"):
            async with unit_of_work():
                pass
