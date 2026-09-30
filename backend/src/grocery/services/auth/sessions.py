"""Выдача, разрешение и отзыв непрозрачных сессий (ADR-0010)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from grocery.config import get_settings
from grocery.db.models import User
from grocery.db.repositories.sessions import session_repo
from grocery.db.repositories.shopping import shopping_list_repo
from grocery.db.repositories.users import user_repo
from grocery.schemas.auth import MeRead, SessionCreate, SessionIssued, ShoppingListRead
from grocery.services.auth.context import get_current_user
from grocery.services.auth.errors import AuthError


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_session(user_id: UUID, device_id: str) -> SessionIssued:
    token = "gl_sess_" + secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().auth.session_ttl_seconds)
    await session_repo.add(
        SessionCreate(
            user_id=user_id,
            token_hash=token_hash(token),
            expires_at=expires_at,
            device_id=device_id,
        )
    )
    return SessionIssued(token=token, expires_at=expires_at)


async def resolve_session(token: str) -> User:
    session = await session_repo.by_token_hash(token_hash(token))
    if session is None or session.expires_at <= datetime.now(UTC):
        raise AuthError("Требуется вход")
    user = await user_repo.get(session.user_id)
    if user is None:
        raise AuthError("Требуется вход")
    return user


async def logout(token: str) -> None:
    session = await session_repo.by_token_hash(token_hash(token))
    if session is not None:
        await session_repo.delete(session)


async def get_me() -> MeRead:
    user = get_current_user()
    shopping_lists = await shopping_list_repo.for_user(user.id)
    return MeRead(
        id=user.id,
        username=user.username,
        shopping_lists=[ShoppingListRead.model_validate(item) for item in shopping_lists],
    )
