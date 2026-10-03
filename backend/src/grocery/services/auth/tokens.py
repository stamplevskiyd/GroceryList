"""Personal tokens and transport-independent bearer identities (ADR-0010)."""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from pydantic import SecretStr

from grocery.config import get_settings
from grocery.db.models import User
from grocery.db.repositories.tokens import token_repo
from grocery.db.repositories.users import user_repo
from grocery.db.session import get_current_session
from grocery.domain.errors import NotFoundError
from grocery.schemas.tokens import BearerIdentity, TokenCreate, TokenIssued, TokenRead, TokenStored
from grocery.services.auth.context import get_current_user
from grocery.services.auth.errors import AuthError
from grocery.services.auth.sessions import token_hash


async def issue_token(data: TokenCreate) -> TokenIssued:
    raw = "gl_pat_" + secrets.token_urlsafe(32)
    stored = await token_repo.add(
        TokenStored(user_id=get_current_user().id, name=data.name, token_hash=token_hash(raw))
    )
    return TokenIssued(**TokenRead.model_validate(stored).model_dump(), token=SecretStr(raw))


async def list_tokens() -> list[TokenRead]:
    return [
        TokenRead.model_validate(token)
        for token in await token_repo.for_user(get_current_user().id)
    ]


async def revoke_token(id: UUID) -> None:
    token = await token_repo.owned(id, get_current_user().id)
    if token is None:
        raise NotFoundError("Токен не найден")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        await get_current_session().flush()


async def verify_bearer(raw: str) -> BearerIdentity | None:
    # OAuth access tokens are added by stage 6. No positive cache: revoke applies
    # to every new HTTP request. Record use independently of the subsequent tool.
    if not raw.startswith("gl_pat_"):
        return None
    token = await token_repo.by_hash(token_hash(raw))
    if token is None or token.revoked_at is not None or await user_repo.get(token.user_id) is None:
        return None
    token.last_used_at = datetime.now(UTC)
    await get_current_session().flush()
    return BearerIdentity(
        user_id=token.user_id,
        client_id=str(token.id),
        client_name=token.name,
        scopes=["shopping_list"],
        resource=get_settings().app.mcp_url,
    )


async def resolve_bearer_user(user_id: UUID) -> User:
    user = await user_repo.get(user_id)
    if user is None:
        raise AuthError("Требуется вход")
    return user
