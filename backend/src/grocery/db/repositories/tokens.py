"""PAT storage; transactions belong to unit_of_work."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from grocery.db.models import PersonalAccessToken
from grocery.db.repositories.base import Repository
from grocery.db.session import get_current_session
from grocery.schemas.tokens import TokenStored


class TokenRepository(Repository[PersonalAccessToken, TokenStored, BaseModel]):
    async def by_hash(self, value: str) -> PersonalAccessToken | None:
        return await get_current_session().scalar(
            select(PersonalAccessToken).where(PersonalAccessToken.token_hash == value)
        )

    async def for_user(self, user_id: UUID) -> list[PersonalAccessToken]:
        return list(
            await get_current_session().scalars(
                select(PersonalAccessToken)
                .where(PersonalAccessToken.user_id == user_id)
                .order_by(PersonalAccessToken.created_at, PersonalAccessToken.id)
            )
        )

    async def owned(self, id: UUID, user_id: UUID) -> PersonalAccessToken | None:
        return await get_current_session().scalar(
            select(PersonalAccessToken).where(
                PersonalAccessToken.id == id, PersonalAccessToken.user_id == user_id
            )
        )


token_repo = TokenRepository(PersonalAccessToken)
