from uuid import UUID

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from grocery.db.base import Entity
from grocery.db.types import PydanticJSON
from grocery.domain.enums import EventType
from grocery.schemas.events import EventPayload
from grocery.schemas.sources import Source


class Event(Entity):
    __tablename__ = "events"
    shopping_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[EventType] = mapped_column(
        Enum(
            EventType,
            native_enum=False,
            length=32,
            values_callable=lambda cls: [v.value for v in cls],
        )
    )
    source: Mapped[Source] = mapped_column(PydanticJSON(Source))
    payload: Mapped[EventPayload] = mapped_column(PydanticJSON(EventPayload))
