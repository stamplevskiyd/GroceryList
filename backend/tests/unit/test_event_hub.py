from datetime import UTC, datetime
from uuid import uuid7

from grocery.domain.enums import EventType
from grocery.schemas.events import EventPayload, EventRead
from grocery.schemas.sources import AppSource
from grocery.services.event_hub import EventHub


def test_slow_consumer_keeps_recent_events_and_subscriptions_release() -> None:
    hub = EventHub(queue_size=1)
    shopping_list_id = uuid7()
    event = EventRead(
        id=uuid7(),
        shopping_list_id=shopping_list_id,
        user_id=uuid7(),
        type=EventType.ITEMS_ADDED,
        source=AppSource(device_id="phone"),
        payload=EventPayload(),
        created_at=datetime.now(UTC),
    )
    with hub.subscribe(shopping_list_id) as slow, hub.subscribe(shopping_list_id) as fast:
        hub.publish(event)
        first = fast.get_nowait()
        next_event = event.model_copy(update={"id": uuid7()})
        hub.publish(next_event)
        assert slow.qsize() == 1
        assert slow.get_nowait().id == next_event.id
        assert fast.get_nowait().id == next_event.id
        first.payload.items.clear()
        assert event.payload == EventPayload()
    hub.publish(event)
    assert slow.empty()
    assert fast.empty()
