"""OAuth queries and locks; all commits stay in unit_of_work."""

import hashlib
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text

from grocery.db.models.oauth import (
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    OAuthGrant,
    OAuthToken,
)
from grocery.db.models.user import User
from grocery.db.repositories.base import Repository
from grocery.db.session import get_current_session
from grocery.schemas.oauth import (
    AuthorizationStored,
    ClientStored,
    CodeStored,
    GrantStored,
    OAuthTokenStored,
)


class ClientRepository(Repository[OAuthClient, ClientStored, BaseModel]):
    async def lock_identity(self, client_id: str) -> None:
        key = int.from_bytes(hashlib.sha256(client_id.encode()).digest()[:8], signed=True)
        await get_current_session().execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
        )

    async def by_client_id(self, client_id: str) -> OAuthClient | None:
        return await get_current_session().scalar(
            select(OAuthClient).where(OAuthClient.client_id == client_id)
        )


class AuthorizationRepository(
    Repository[OAuthAuthorizationRequest, AuthorizationStored, BaseModel]
):
    async def locked(self, id: UUID) -> OAuthAuthorizationRequest | None:
        return await get_current_session().scalar(
            select(OAuthAuthorizationRequest)
            .where(OAuthAuthorizationRequest.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )


class GrantRepository(Repository[OAuthGrant, GrantStored, BaseModel]):
    async def locked(self, id: UUID) -> OAuthGrant | None:
        return await get_current_session().scalar(
            select(OAuthGrant)
            .where(OAuthGrant.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def lock_user(self, user_id: UUID) -> None:
        await get_current_session().scalar(select(User).where(User.id == user_id).with_for_update())

    async def for_user(self, user_id: UUID, client_pk: UUID | None = None) -> list[OAuthGrant]:
        query = select(OAuthGrant).where(OAuthGrant.user_id == user_id).order_by(OAuthGrant.id)
        if client_pk is not None:
            query = query.where(OAuthGrant.client_pk == client_pk).with_for_update()
        return list(
            await get_current_session().scalars(query.execution_options(populate_existing=True))
        )


class CodeRepository(Repository[OAuthCode, CodeStored, BaseModel]):
    async def by_hash(self, hashed: str) -> OAuthCode | None:
        return await get_current_session().scalar(
            select(OAuthCode)
            .where(OAuthCode.token_hash == hashed)
            .with_for_update()
            .execution_options(populate_existing=True)
        )


class OAuthTokenRepository(Repository[OAuthToken, OAuthTokenStored, BaseModel]):
    async def by_hash(self, hashed: str, *, refresh: bool = False) -> OAuthToken | None:
        column = OAuthToken.refresh_token_hash if refresh else OAuthToken.access_token_hash
        return await get_current_session().scalar(
            select(OAuthToken).where(column == hashed).execution_options(populate_existing=True)
        )


client_repo = ClientRepository(OAuthClient)
authorization_repo = AuthorizationRepository(OAuthAuthorizationRequest)
grant_repo = GrantRepository(OAuthGrant)
code_repo = CodeRepository(OAuthCode)
oauth_token_repo = OAuthTokenRepository(OAuthToken)
