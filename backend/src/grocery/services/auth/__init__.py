"""Контекст пользователя и первичное создание учётной записи (ADR-0003)."""

from grocery.db.models import User
from grocery.db.repositories.shopping import member_repo, shopping_list_repo
from grocery.db.repositories.users import user_repo
from grocery.domain.enums import MemberRole
from grocery.domain.errors import ConflictError, InvalidInputError
from grocery.schemas.auth import LoginResult, RegistrationCreate
from grocery.schemas.shopping_lists import MemberCreate, ShoppingListCreate
from grocery.schemas.users import UserCreate
from grocery.services.auth.context import acting_as, get_current_user
from grocery.services.auth.errors import AuthError, TooManyAttemptsError
from grocery.services.auth.passwords import hash_password, initialize_passwords, verify_password
from grocery.services.auth.rate_limit import get_login_limiter
from grocery.services.auth.sessions import get_me, issue_session, login, logout, resolve_session

__all__ = [
    "AuthError",
    "TooManyAttemptsError",
    "acting_as",
    "create_user",
    "get_current_user",
    "get_me",
    "initialize_passwords",
    "issue_session",
    "login",
    "logout",
    "register",
    "resolve_session",
    "verify_password",
]


async def create_user(username: str, password: str) -> User:
    username = username.strip()
    if not username or len(username) > 64 or not password:
        raise InvalidInputError("Нужны логин (до 64 символов) и непустой пароль")
    if await user_repo.by_username(username) is not None:
        raise ConflictError("Пользователь с таким логином уже существует")
    user = await user_repo.create_if_available(
        UserCreate(username=username, password_hash=await hash_password(password))
    )
    if user is None:
        raise ConflictError("Пользователь с таким логином уже существует")
    shopping_list = await shopping_list_repo.add(
        ShoppingListCreate(name="Покупки", owner_id=user.id)
    )
    await member_repo.add(
        MemberCreate(shopping_list_id=shopping_list.id, user_id=user.id, role=MemberRole.OWNER)
    )
    return user


async def register(data: RegistrationCreate, *, device_id: str, ip: str) -> LoginResult:
    try:
        # Share the IP budget with login; the username budget is registration-specific.
        get_login_limiter().reserve(username="register:" + data.username, ip=ip)
    except TooManyAttemptsError as exc:
        raise TooManyAttemptsError(
            exc.retry_after, message="Слишком много попыток регистрации"
        ) from exc
    user = await create_user(data.username, data.password)
    session = await issue_session(user.id, device_id)
    with acting_as(user):
        return LoginResult(session=session, me=await get_me())
