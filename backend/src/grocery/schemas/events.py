from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
