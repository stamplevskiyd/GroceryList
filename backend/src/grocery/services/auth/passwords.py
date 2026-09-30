"""Argon2 вне event loop, включая проверку неизвестного пользователя."""

import asyncio
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()
_dummy_hash: str | None = None
_dummy_lock = asyncio.Lock()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def _get_dummy_hash() -> str:
    global _dummy_hash
    # Инициализируем один раз при первом использовании, также вне event loop.
    async with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = await hash_password(secrets.token_urlsafe(32))
        return _dummy_hash


async def initialize_passwords() -> None:
    """Подготовить dummy hash при запуске приложения до приёма попыток входа."""
    await _get_dummy_hash()


async def verify_password(password: str, password_hash: str | None) -> bool:
    candidate_hash = password_hash if password_hash is not None else await _get_dummy_hash()
    try:
        verified = await asyncio.to_thread(_hasher.verify, candidate_hash, password)
    except VerifyMismatchError:
        return False
    # Повреждённые хеши намеренно не превращаем в неверный пароль.
    return verified and password_hash is not None
