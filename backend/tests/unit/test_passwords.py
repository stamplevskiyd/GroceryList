import threading
from collections.abc import Callable

import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from grocery.services.auth.passwords import hash_password, initialize_passwords, verify_password


async def test_correct_and_incorrect_passwords() -> None:
    password_hash = await hash_password("correct-password")
    assert password_hash != "correct-password"
    assert await verify_password("correct-password", password_hash) is True
    assert await verify_password("wrong-password", password_hash) is False


async def test_initialization_prewarms_dummy_hash_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from grocery.services.auth import passwords

    monkeypatch.setattr(passwords, "_dummy_hash", None)
    seen: list[str] = []
    original_hash = PasswordHasher.hash

    def hash_password(self: PasswordHasher, password: str) -> str:
        seen.append(password)
        return original_hash(self, password)

    monkeypatch.setattr(PasswordHasher, "hash", hash_password)
    await initialize_passwords()
    await initialize_passwords()
    assert await verify_password("unknown-password", None) is False
    assert len(seen) == 1


async def test_unknown_user_verifies_dummy_hash_with_same_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_hash = await hash_password("correct-password")
    seen: list[str] = []

    def verify(self: PasswordHasher, candidate_hash: str, password: str) -> bool:
        seen.append(candidate_hash)
        raise VerifyMismatchError("mismatch")

    monkeypatch.setattr(PasswordHasher, "verify", verify)
    assert await verify_password("password", None) is False
    assert await verify_password("password", None) is False
    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert extract_parameters(seen[0]) == extract_parameters(password_hash)


async def test_corrupt_stored_hash_is_internal_failure() -> None:
    with pytest.raises(InvalidHashError):
        await verify_password("password", "corrupt-hash")


async def test_argon2_hash_and_verify_run_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []
    original_hash = PasswordHasher.hash
    original_verify = PasswordHasher.verify

    def track[T](fn: Callable[..., T]) -> Callable[..., T]:
        def tracked(*args: object, **kwargs: object) -> T:
            worker_threads.append(threading.get_ident())
            return fn(*args, **kwargs)

        return tracked

    monkeypatch.setattr(PasswordHasher, "hash", track(original_hash))
    monkeypatch.setattr(PasswordHasher, "verify", track(original_verify))
    password_hash = await hash_password("password")
    assert await verify_password("password", password_hash) is True
    assert len(worker_threads) == 2
    assert all(thread != event_loop_thread for thread in worker_threads)
