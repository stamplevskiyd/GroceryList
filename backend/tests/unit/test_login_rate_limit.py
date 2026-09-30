import asyncio
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from grocery.config import get_settings
from grocery.schemas.auth import LoginCreate
from grocery.services.auth import TooManyAttemptsError
from grocery.services.auth.rate_limit import LoginLimiter, get_login_limiter


@pytest.fixture(autouse=True)
def _fresh_limiter() -> Iterator[None]:
    get_login_limiter.cache_clear()
    yield
    get_login_limiter.cache_clear()


def test_username_limit_works_across_ips() -> None:
    limiter = LoginLimiter(username_limit=2, ip_limit=30, window_seconds=300, clock=lambda: 100.0)
    limiter.reserve(username="anna", ip="192.0.2.1")
    limiter.reserve(username="anna", ip="192.0.2.2")
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="anna", ip="192.0.2.3")
    assert error.value.retry_after == 300


def test_ip_limit_works_across_usernames() -> None:
    limiter = LoginLimiter(username_limit=5, ip_limit=2, window_seconds=300, clock=lambda: 100.0)
    limiter.reserve(username="anna", ip="192.0.2.1")
    limiter.reserve(username="boris", ip="192.0.2.1")
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="carol", ip="192.0.2.1")
    assert error.value.retry_after == 300


def test_retry_after_uses_latest_necessary_release_and_rounds_up() -> None:
    now = 100.0
    limiter = LoginLimiter(username_limit=1, ip_limit=1, window_seconds=300, clock=lambda: now)
    limiter.reserve(username="anna", ip="first")
    now = 120.0
    limiter.reserve(username="boris", ip="second")
    now = 130.5
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="anna", ip="second")
    assert error.value.retry_after == 290
    now = 400.0
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="anna", ip="second")
    assert error.value.retry_after == 20
    now = 420.0
    limiter.reserve(username="anna", ip="second")


def test_sliding_window_releases_only_expired_attempts() -> None:
    now = 100.0
    limiter = LoginLimiter(username_limit=2, ip_limit=30, window_seconds=300, clock=lambda: now)
    limiter.reserve(username="anna", ip="first")
    now = 150.0
    limiter.reserve(username="anna", ip="first")
    now = 400.0
    limiter.reserve(username="anna", ip="first")
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="anna", ip="first")
    assert error.value.retry_after == 50


def test_rejected_attempt_does_not_consume_other_bucket() -> None:
    limiter = LoginLimiter(username_limit=1, ip_limit=1, window_seconds=300, clock=lambda: 100.0)
    limiter.reserve(username="anna", ip="first")
    with pytest.raises(TooManyAttemptsError):
        limiter.reserve(username="anna", ip="second")
    limiter.reserve(username="boris", ip="second")


def test_capacity_denial_preserves_active_keys_and_creates_no_partial_bucket() -> None:
    limiter = LoginLimiter(
        username_limit=2, ip_limit=2, window_seconds=300, max_keys=3, clock=lambda: 100.0
    )
    limiter.reserve(username="anna", ip="first")
    for _ in range(3):
        with pytest.raises(TooManyAttemptsError) as error:
            limiter.reserve(username="boris", ip="second")
        assert error.value.retry_after == 300
    limiter.reserve(username="boris", ip="first")
    with pytest.raises(TooManyAttemptsError):
        limiter.reserve(username="anna", ip="first")


def test_capacity_retry_waits_until_enough_whole_buckets_expire() -> None:
    now = 100.0
    limiter = LoginLimiter(
        username_limit=5, ip_limit=30, window_seconds=300, max_keys=3, clock=lambda: now
    )
    limiter.reserve(username="anna", ip="first")
    now = 120.0
    limiter.reserve(username="boris", ip="first")
    now = 130.0
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="carol", ip="second")
    assert error.value.retry_after == 290
    now = 400.0
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="carol", ip="second")
    assert error.value.retry_after == 20
    now = 420.0
    limiter.reserve(username="carol", ip="second")
    limiter.reserve(username="dave", ip="second")


def test_key_namespaces_are_independent() -> None:
    limiter = LoginLimiter(username_limit=1, ip_limit=1, window_seconds=300, clock=lambda: 100.0)
    limiter.reserve(username="same", ip="other")
    limiter.reserve(username="other", ip="same")


async def test_exactly_five_parallel_attempts_are_reserved() -> None:
    limiter = LoginLimiter(username_limit=5, ip_limit=30, window_seconds=300, clock=lambda: 100.0)

    async def attempt(index: int) -> bool:
        try:
            limiter.reserve(username="anna", ip=str(index))
        except TooManyAttemptsError:
            return False
        await asyncio.sleep(0)
        return True

    assert sum(await asyncio.gather(*(attempt(index) for index in range(12)))) == 5


def test_process_factory_is_cached_and_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_LOGIN_USERNAME_LIMIT", "1")
    monkeypatch.setenv("AUTH_LOGIN_IP_LIMIT", "1")
    monkeypatch.setenv("AUTH_LOGIN_WINDOW_SECONDS", "600")
    get_settings.cache_clear()
    limiter = get_login_limiter()
    assert get_login_limiter() is limiter
    limiter.reserve(username="anna", ip="first")
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="anna", ip="second")
    assert error.value.retry_after == 600
    with pytest.raises(TooManyAttemptsError):
        limiter.reserve(username="boris", ip="first")


def test_login_schema_trims_username_and_keeps_password_secret() -> None:
    data = LoginCreate(username=" anna ", password=" password ")
    assert data.username == "anna"
    assert data.password == " password "
    assert "password" not in repr(data)
    assert LoginCreate(username="a" * 64, password="p").username == "a" * 64


@pytest.mark.parametrize("username", ["", "  ", "a" * 65])
def test_login_schema_rejects_invalid_usernames(username: str) -> None:
    with pytest.raises(ValidationError):
        LoginCreate(username=username, password="p")


def test_login_schema_rejects_empty_password_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LoginCreate(username="anna", password="")
    with pytest.raises(ValidationError):
        LoginCreate.model_validate({"username": "anna", "password": "p", "source": "spoofed"})


def test_capacity_retry_does_not_count_expiry_of_required_key_as_free_slot() -> None:
    now = 100.0
    limiter = LoginLimiter(
        username_limit=5, ip_limit=30, window_seconds=300, max_keys=3, clock=lambda: now
    )
    limiter.reserve(username="anna", ip="first")
    now = 120.0
    limiter.reserve(username="boris", ip="first")
    now = 130.0
    with pytest.raises(TooManyAttemptsError) as error:
        limiter.reserve(username="anna", ip="second")
    assert error.value.retry_after == 290
