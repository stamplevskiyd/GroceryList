"""PAT contracts: public metadata and one-time secret issuance."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, field_serializer


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, AfterValidator(str.strip), Field(min_length=1, max_length=255)]


class TokenStored(BaseModel):
    user_id: UUID
    name: str
    token_hash: str = Field(repr=False)


class TokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class TokenIssued(TokenRead):
    token: SecretStr

    @field_serializer("token", when_used="json")
    def serialize_token(self, token: SecretStr) -> str:
        # This response is the only place a PAT secret is deliberately revealed.
        return token.get_secret_value()


class BearerIdentity(BaseModel):
    user_id: UUID
    client_id: str
    client_name: str
    scopes: list[str]
    resource: str
