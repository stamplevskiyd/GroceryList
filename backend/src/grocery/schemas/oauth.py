"""OAuth wire contracts and persisted request parameters."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer

from grocery.domain.enums import ClientRegistration


class ClientMetadata(BaseModel):
    # RFC 7591 permits additional client metadata. We store only supported fields.
    client_name: str = Field(min_length=1, max_length=255)
    redirect_uris: list[str] = Field(min_length=1, max_length=20)
    token_endpoint_auth_method: Literal["none"] = "none"  # noqa: S105 — protocol value
    grant_types: list[Literal["authorization_code", "refresh_token"]] = [
        "authorization_code",
        "refresh_token",
    ]
    response_types: list[Literal["code"]] = ["code"]


class ClientDocument(ClientMetadata):
    client_id: str = Field(min_length=1, max_length=2048)


class ClientRegistered(ClientDocument):
    client_id_issued_at: int


class AuthorizationParams(BaseModel):
    client_id: str = Field(min_length=1, max_length=2048)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    response_type: str
    code_challenge: str = Field(min_length=1, max_length=128)
    code_challenge_method: str
    resource: str = Field(min_length=1, max_length=2048)
    scope: str = Field(default="shopping_list", max_length=255)
    state: str | None = Field(default=None, max_length=2048)


class ConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    allow: bool


class ConsentRead(BaseModel):
    request_id: UUID
    client_name: str
    redirect_uri: str
    redirect_host: str
    loopback: bool
    scopes: list[str]
    expires_at: datetime


class AuthorizationStarted(BaseModel):
    request_id: UUID
    browser_token: str = Field(repr=False)


class RedirectRead(BaseModel):
    redirect_url: str


class OAuthFailure(BaseModel):
    error: str
    error_description: str


class OAuthTokenRead(BaseModel):
    access_token: SecretStr
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 — protocol value
    expires_in: int
    scope: str
    refresh_token: SecretStr | None = None

    @field_serializer("access_token", "refresh_token", when_used="json")
    def serialize_secret(self, value: SecretStr | None) -> str | None:
        return value.get_secret_value() if value is not None else None


class TokenRequest(BaseModel):
    grant_type: str
    client_id: str = Field(min_length=1, max_length=2048)
    resource: str = Field(min_length=1, max_length=2048)
    code: str = Field(default="", max_length=256, repr=False)
    redirect_uri: str = Field(default="", max_length=2048)
    code_verifier: str = Field(default="", max_length=128, repr=False)
    refresh_token: str = Field(default="", max_length=256, repr=False)
    scope: str | None = Field(default=None, max_length=255)


class RevokeRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=2048)
    token: str = Field(min_length=1, max_length=256, repr=False)
    token_type_hint: str | None = None


class ConnectionRead(BaseModel):
    id: UUID
    client_id: str
    client_name: str
    connected_at: datetime
    scopes: list[str]


class ClientStored(BaseModel):
    client_id: str
    client_metadata: ClientMetadata
    registration_type: ClientRegistration
    cache_expires_at: datetime | None = None


class AuthorizationStored(BaseModel):
    client_pk: UUID
    params: AuthorizationParams
    browser_token_hash: str
    expires_at: datetime


class GrantStored(BaseModel):
    client_pk: UUID
    user_id: UUID
    scope: str
    resource: str
    expires_at: datetime


class CodeStored(BaseModel):
    token_hash: str
    family_id: UUID
    redirect_uri: str
    code_challenge: str
    expires_at: datetime


class OAuthTokenStored(BaseModel):
    family_id: UUID
    access_token_hash: str
    refresh_token_hash: str | None
    expires_at: datetime


class OAuthMetadata(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    revocation_endpoint: str
    response_types_supported: list[str] = ["code"]
    grant_types_supported: list[str] = ["authorization_code", "refresh_token"]
    code_challenge_methods_supported: list[str] = ["S256"]
    token_endpoint_auth_methods_supported: list[str] = ["none"]
    revocation_endpoint_auth_methods_supported: list[str] = ["none"]
    scopes_supported: list[str] = ["shopping_list", "offline_access"]
    client_id_metadata_document_supported: bool = True
    authorization_response_iss_parameter_supported: bool = True
