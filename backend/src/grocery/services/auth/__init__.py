"""Контекст пользователя и первичное создание учётной записи (ADR-0003)."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from argon2 import PasswordHasher

from grocery.db.models import User
from grocery.db.repositories.shopping import member_repo, shopping_list_repo
from grocery.db.repositories.users import user_repo
from grocery.domain.enums import MemberRole
from grocery.domain.errors import ConflictError, InvalidInputError
from grocery.schemas.shopping_lists import MemberCreate, ShoppingListCreate
from grocery.schemas.users import UserCreate


class AuthError(Exception):
    pass


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


async def create_user(username: str, password: str) -> User:
    username = username.strip()
    if not username or len(username) > 64 or not password:
        raise InvalidInputError("Нужны логин (до 64 символов) и непустой пароль")
    if await user_repo.by_username(username) is not None:
        raise ConflictError("Пользователь с таким логином уже существует")
    user = await user_repo.add(
        UserCreate(username=username, password_hash=PasswordHasher().hash(password))
    )
    shopping_list = await shopping_list_repo.add(
        ShoppingListCreate(name="Покупки", owner_id=user.id)
    )
    await member_repo.add(
        MemberCreate(shopping_list_id=shopping_list.id, user_id=user.id, role=MemberRole.OWNER)
    )
    return user
