from uuid import UUID

from pydantic import BaseModel

from grocery.domain.enums import MemberRole


class ShoppingListCreate(BaseModel):
    name: str
    owner_id: UUID


class ShoppingListUpdate(BaseModel):
    name: str | None = None


class MemberCreate(BaseModel):
    shopping_list_id: UUID
    user_id: UUID
    role: MemberRole
