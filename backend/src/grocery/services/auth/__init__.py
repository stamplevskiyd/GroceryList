"""Контекст пользователя и первичное создание учётной записи (ADR-0003)."""

from grocery.db.models import User
from grocery.db.repositories.shopping import member_repo, shopping_list_repo
from grocery.db.repositories.users import user_repo
from grocery.domain.enums import MemberRole
from grocery.domain.errors import ConflictError, InvalidInputError
from grocery.schemas.shopping_lists import MemberCreate, ShoppingListCreate
from grocery.schemas.users import UserCreate
from grocery.services.auth.context import acting_as, get_current_user
from grocery.services.auth.errors import AuthError
from grocery.services.auth.passwords import hash_password, initialize_passwords, verify_password
from grocery.services.auth.sessions import get_me, issue_session, logout, resolve_session

__all__ = [
    "AuthError",
    "acting_as",
    "create_user",
    "get_current_user",
    "get_me",
    "initialize_passwords",
    "issue_session",
    "logout",
    "resolve_session",
    "verify_password",
]


async def create_user(username: str, password: str) -> User:
    username = username.strip()
    if not username or len(username) > 64 or not password:
        raise InvalidInputError("Нужны логин (до 64 символов) и непустой пароль")
    if await user_repo.by_username(username) is not None:
        raise ConflictError("Пользователь с таким логином уже существует")
    user = await user_repo.add(
        UserCreate(username=username, password_hash=await hash_password(password))
    )
    shopping_list = await shopping_list_repo.add(
        ShoppingListCreate(name="Покупки", owner_id=user.id)
    )
    await member_repo.add(
        MemberCreate(shopping_list_id=shopping_list.id, user_id=user.id, role=MemberRole.OWNER)
    )
    return user
