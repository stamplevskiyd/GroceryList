"""Пользователь текущей единицы работы (ADR-0003)."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from grocery.db.models import User
from grocery.services.auth.errors import AuthError

_current_user: ContextVar[User | None] = ContextVar("current_user", default=None)


def get_current_user() -> User:
    user = _current_user.get()
    if user is None:
        raise AuthError("Требуется вход")
    return user


@contextmanager
def acting_as(user: User) -> Iterator[None]:
    token = _current_user.set(user)
    try:
        yield
    finally:
        _current_user.reset(token)
