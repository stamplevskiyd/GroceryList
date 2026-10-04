"""OAuth clients and grants. Raw credentials never enter these tables."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from grocery.db.base import Entity
from grocery.db.types import PydanticJSON
from grocery.domain.enums import ClientRegistration
from grocery.schemas.oauth import AuthorizationParams, ClientMetadata


class OAuthClient(Entity):
    __tablename__ = "oauth_clients"
    client_id: Mapped[str] = mapped_column(String(2048), unique=True)
    client_metadata: Mapped[ClientMetadata] = mapped_column(PydanticJSON(ClientMetadata))
    registration_type: Mapped[ClientRegistration] = mapped_column(
        Enum(
            ClientRegistration,
            native_enum=False,
            length=32,
            values_callable=lambda cls: [value.value for value in cls],
            validate_strings=True,
        )
    )
    cache_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthAuthorizationRequest(Entity):
    __tablename__ = "oauth_authorization_requests"
    client_pk: Mapped[UUID] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    params: Mapped[AuthorizationParams] = mapped_column(PydanticJSON(AuthorizationParams))
    browser_token_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthGrant(Entity):
    """One consent and its refresh family; the row is the family-wide lock."""

    __tablename__ = "oauth_grants"
    client_pk: Mapped[UUID] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(255))
    resource: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthCode(Entity):
    __tablename__ = "oauth_codes"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("oauth_grants.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    code_challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthToken(Entity):
    __tablename__ = "oauth_tokens"
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
    )
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Access-only revocation. Refresh/family revocation lives on OAuthGrant.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
