"""unit_of_work: коммит, откат, контекст, хуки после коммита (ADR-0004)."""

import logging

import pytest
from sqlalchemy import func, select

from grocery.db.models import User
from grocery.db.session import get_current_session, on_commit, unit_of_work


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


async def test_hooks_run_after_commit_in_order() -> None:
    calls: list[str] = []

    async def first() -> None:
        # Хук выполняется вне единицы работы и видит закоммиченные данные.
        calls.append(f"first:{await _count_users()}")

    async def second() -> None:
        calls.append("second")

    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))
        on_commit(first)
        on_commit(second)
        assert calls == []

    assert calls == ["first:1", "second"]


async def test_hooks_do_not_run_on_rollback() -> None:
    calls: list[str] = []

    async def hook() -> None:
        calls.append("called")

    async def register_hook_then_fail() -> None:
        async with unit_of_work():
            on_commit(hook)
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await register_hook_then_fail()

    assert calls == []


async def test_failing_hook_is_logged_and_others_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    async def failing() -> None:
        raise RuntimeError("sse down")

    async def next_hook() -> None:
        calls.append("next")

    with caplog.at_level(logging.ERROR, logger="grocery.db.session"):
        async with unit_of_work():
            on_commit(failing)
            on_commit(next_hook)

    assert calls == ["next"]
    assert "sse down" in caplog.text


async def test_on_commit_outside_unit_of_work_raises() -> None:
    async def hook() -> None:
        return None

    with pytest.raises(RuntimeError, match="unit_of_work"):
        on_commit(hook)
