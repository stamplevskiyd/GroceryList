"""Запись в транзакции и публикация после её успешного завершения (ADR-0004)."""

from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction

from grocery.db.repositories.shopping import event_repo
from grocery.db.session import get_current_session
from grocery.domain.enums import EventType
from grocery.schemas.events import EventCreate, EventPayload, EventRead
from grocery.schemas.sources import Source
from grocery.services.auth import get_current_user
from grocery.services.event_hub import event_hub


async def record_event(
    shopping_list_id: UUID, type: EventType, source: Source, payload: EventPayload
) -> EventRead:
    stored = await event_repo.add(
        EventCreate(
            shopping_list_id=shopping_list_id,
            user_id=get_current_user().id,
            type=type,
            source=source,
            payload=payload,
        )
    )
    snapshot = EventRead.model_validate(stored).model_copy(deep=True)
    session = get_current_session().sync_session
    pending = True

    def publish_after_commit(session: Session) -> None:
        nonlocal pending
        if pending and not session.in_nested_transaction():
            pending = False
            event_hub.publish(snapshot)

    def discard_after_rollback(session: Session, transaction: SessionTransaction) -> None:
        nonlocal pending
        pending = False

    event.listen(session, "after_commit", publish_after_commit)
    event.listen(session, "after_soft_rollback", discard_after_rollback)
    return snapshot
