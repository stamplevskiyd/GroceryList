"""Все ORM-модели. Импорт пакета регистрирует их в Base.metadata (нужно Alembic)."""

from grocery.db.models.auth import PersonalAccessToken, Session
from grocery.db.models.event import Event
from grocery.db.models.oauth import (
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    OAuthGrant,
    OAuthToken,
)
from grocery.db.models.shopping import Item, ShoppingList, ShoppingListMember, Tag
from grocery.db.models.user import User

__all__ = [
    "Event",
    "Item",
    "OAuthAuthorizationRequest",
    "OAuthClient",
    "OAuthCode",
    "OAuthGrant",
    "OAuthToken",
    "PersonalAccessToken",
    "Session",
    "ShoppingList",
    "ShoppingListMember",
    "Tag",
    "User",
]
