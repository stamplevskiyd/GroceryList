"""Хранилище cookie-сессий без управления транзакциями."""

from pydantic import BaseModel
from sqlalchemy import select

from grocery.db.models import Session
from grocery.db.repositories.base import Repository
from grocery.db.session import get_current_session
from grocery.schemas.auth import SessionCreate


class SessionRepository(Repository[Session, SessionCreate, BaseModel]):
    async def by_token_hash(self, token_hash: str) -> Session | None:
        return await get_current_session().scalar(
            select(Session).where(Session.token_hash == token_hash)
        )


session_repo = SessionRepository(Session)
