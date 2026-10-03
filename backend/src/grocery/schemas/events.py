from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from grocery.domain.enums import EventType
from grocery.schemas.items import AddItemResult, ItemRead
from grocery.schemas.sources import Source
from grocery.schemas.tags import TagRead


class ItemsAddedPayload(BaseModel):
    results: list[AddItemResult]


class ItemsPayload(BaseModel):
    items: list[ItemRead]


class TagChangedPayload(BaseModel):
    tag: TagRead
    previous_tag: TagRead


class TagDeletedPayload(BaseModel):
    tag: TagRead


EventPayload = ItemsAddedPayload | ItemsPayload | TagChangedPayload | TagDeletedPayload

PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.ITEMS_ADDED: ItemsAddedPayload,
    EventType.ITEM_UPDATED: ItemsPayload,
    EventType.ITEMS_BOUGHT: ItemsPayload,
    EventType.ITEMS_UNBOUGHT: ItemsPayload,
    EventType.ITEMS_DELETED: ItemsPayload,
    EventType.BOUGHT_CLEARED: ItemsPayload,
    EventType.TAG_RENAMED: TagChangedPayload,
    EventType.TAGS_MERGED: TagChangedPayload,
    EventType.TAG_DELETED: TagDeletedPayload,
}


class EventCreate(BaseModel):
    shopping_list_id: UUID
    user_id: UUID
    type: EventType
    source: Source
    payload: EventPayload

    @model_validator(mode="after")
    def payload_matches_type(self) -> EventCreate:
        expected = PAYLOAD_MODELS[self.type]
        if not isinstance(self.payload, expected):
            raise ValueError("Payload не соответствует типу события")
        return self


class EventRead(EventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


class ItemsAddedEvent(EventRead):
    payload: ItemsAddedPayload
    type: Literal[EventType.ITEMS_ADDED] = EventType.ITEMS_ADDED


class ItemUpdatedEvent(EventRead):
    payload: ItemsPayload
    type: Literal[EventType.ITEM_UPDATED] = EventType.ITEM_UPDATED


class ItemsBoughtEvent(EventRead):
    payload: ItemsPayload
    type: Literal[EventType.ITEMS_BOUGHT] = EventType.ITEMS_BOUGHT


class ItemsUnboughtEvent(EventRead):
    payload: ItemsPayload
    type: Literal[EventType.ITEMS_UNBOUGHT] = EventType.ITEMS_UNBOUGHT


class ItemsDeletedEvent(EventRead):
    payload: ItemsPayload
    type: Literal[EventType.ITEMS_DELETED] = EventType.ITEMS_DELETED


class BoughtClearedEvent(EventRead):
    payload: ItemsPayload
    type: Literal[EventType.BOUGHT_CLEARED] = EventType.BOUGHT_CLEARED


class TagRenamedEvent(EventRead):
    payload: TagChangedPayload
    type: Literal[EventType.TAG_RENAMED] = EventType.TAG_RENAMED


class TagsMergedEvent(EventRead):
    payload: TagChangedPayload
    type: Literal[EventType.TAGS_MERGED] = EventType.TAGS_MERGED


class TagDeletedEvent(EventRead):
    payload: TagDeletedPayload
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
