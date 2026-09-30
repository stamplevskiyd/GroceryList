import asyncio
from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select

from grocery.db.models import Session, User
from grocery.db.session import unit_of_work
from grocery.schemas.auth import LoginCreate
from grocery.services.auth import AuthError, TooManyAttemptsError, create_user, login
from grocery.services.auth.rate_limit import get_login_limiter
from grocery.services.auth.sessions import resolve_session


@pytest.fixture(autouse=True)
def _fresh_limiter() -> Iterator[None]:
    get_login_limiter.cache_clear()
    yield
    get_login_limiter.cache_clear()


@pytest.fixture
async def owner() -> User:
    async with unit_of_work():
        return await create_user("anna", "password")


async def test_login_issues_fresh_session_and_public_me(owner: User) -> None:
    async with unit_of_work():
        first = await login(
            LoginCreate(username=" anna ", password="password"), device_id="phone", ip="first"
        )
        second = await login(
            LoginCreate(username="anna", password="password"), device_id="phone", ip="first"
        )
    assert first.session.token != second.session.token
    assert first.me.id == owner.id
    assert first.me.username == "anna"
    assert len(first.me.shopping_lists) == 1
    assert first.me.shopping_lists[0].name == "Покупки"
    assert owner.password_hash not in first.me.model_dump_json()
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 2
        assert (await resolve_session(first.session.token)).id == owner.id
        assert (await resolve_session(second.session.token)).id == owner.id


@pytest.mark.parametrize(
    ("username", "password"), [("anna", "wrong"), ("missing", "password"), ("Anna", "password")]
)
async def test_invalid_credentials_have_same_error_and_create_no_session(
    owner: User, username: str, password: str
) -> None:
    with pytest.raises(AuthError) as error:
        async with unit_of_work():
            await login(
                LoginCreate(username=username, password=password), device_id="phone", ip="first"
            )
    assert error.value.code == "invalid_credentials"
    assert str(error.value) == "Неверный логин или пароль"
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 0


async def test_successful_logins_count_and_limit_precedes_argon2(
    owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(5):
        async with unit_of_work():
            await login(
                LoginCreate(username="anna", password="password"), device_id="phone", ip=str(index)
            )

    def unexpected_verify(self: PasswordHasher, candidate_hash: str, password: str) -> bool:
        pytest.fail("throttled login reached Argon2")

    monkeypatch.setattr(PasswordHasher, "verify", unexpected_verify)
    with pytest.raises(TooManyAttemptsError) as error:
        async with unit_of_work():
            await login(
                LoginCreate(username="anna", password="password"), device_id="phone", ip="new"
            )
    assert error.value.retry_after >= 1
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 5


async def test_failed_login_reservations_survive_rollback(owner: User) -> None:
    for index in range(5):
        with pytest.raises(AuthError):
            async with unit_of_work():
                await login(
                    LoginCreate(username="anna", password="wrong"), device_id="phone", ip=str(index)
                )
    with pytest.raises(TooManyAttemptsError):
        async with unit_of_work():
            await login(
                LoginCreate(username="anna", password="password"), device_id="phone", ip="new"
            )
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 0


async def test_successful_login_rollback_does_not_release_reservation(
    owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_LOGIN_USERNAME_LIMIT", "1")
    with pytest.raises(RuntimeError, match="rollback"):  # noqa: PT012 — проверка отката UoW
        async with unit_of_work():
            await login(
                LoginCreate(username="anna", password="password"), device_id="phone", ip="first"
            )
            raise RuntimeError("rollback")
    with pytest.raises(TooManyAttemptsError):
        async with unit_of_work():
            await login(
                LoginCreate(username="anna", password="password"), device_id="phone", ip="second"
            )
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 0


@pytest.mark.real_commits
async def test_parallel_logins_allow_exactly_five_before_first_await(owner: User) -> None:
    async def attempt(index: int) -> bool:
        try:
            async with unit_of_work():
                await login(
                    LoginCreate(username="anna", password="password"),
                    device_id="phone",
                    ip=str(index),
                )
        except TooManyAttemptsError:
            return False
        return True

    assert sum(await asyncio.gather(*(attempt(index) for index in range(12)))) == 5
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 5
