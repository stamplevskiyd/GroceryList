from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel

from grocery.domain.enums import EventType
from grocery.schemas.items import AddItemResult, ItemRead, TagRead
from grocery.schemas.sources import Source


class EventPayload(BaseModel):
    items: list[ItemRead] = Field(default_factory=list)
    results: list[AddItemResult] = Field(default_factory=list)
    tag: TagRead | None = None
    previous_tag: TagRead | None = None


class EventCreate(BaseModel):
    shopping_list_id: UUID
    user_id: UUID
    type: EventType
    source: Source
    payload: EventPayload


class EventRead(EventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


class ItemsAddedEvent(EventRead):
    type: Literal[EventType.ITEMS_ADDED] = EventType.ITEMS_ADDED


class ItemUpdatedEvent(EventRead):
    type: Literal[EventType.ITEM_UPDATED] = EventType.ITEM_UPDATED


class ItemsBoughtEvent(EventRead):
    type: Literal[EventType.ITEMS_BOUGHT] = EventType.ITEMS_BOUGHT


class ItemsUnboughtEvent(EventRead):
    type: Literal[EventType.ITEMS_UNBOUGHT] = EventType.ITEMS_UNBOUGHT


class ItemsDeletedEvent(EventRead):
    type: Literal[EventType.ITEMS_DELETED] = EventType.ITEMS_DELETED


class BoughtClearedEvent(EventRead):
    type: Literal[EventType.BOUGHT_CLEARED] = EventType.BOUGHT_CLEARED


class TagRenamedEvent(EventRead):
    type: Literal[EventType.TAG_RENAMED] = EventType.TAG_RENAMED


class TagsMergedEvent(EventRead):
    type: Literal[EventType.TAGS_MERGED] = EventType.TAGS_MERGED


class TagDeletedEvent(EventRead):
    type: Literal[EventType.TAG_DELETED] = EventType.TAG_DELETED


ShoppingListEvent = Annotated[
    ItemsAddedEvent
    | ItemUpdatedEvent
    | ItemsBoughtEvent
    | ItemsUnboughtEvent
    | ItemsDeletedEvent
    | BoughtClearedEvent
    | TagRenamedEvent
    | TagsMergedEvent
    | TagDeletedEvent,
    Field(discriminator="type"),
]


class ShoppingListEventRead(RootModel[ShoppingListEvent]):
    """Named SSE contract; serialized as the original event object."""
