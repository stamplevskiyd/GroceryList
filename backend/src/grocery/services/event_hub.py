"""SSE-хаб одного процесса. Не держит сессии БД; подписка всегда освобождается."""

from asyncio import Queue
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from grocery.schemas.events import EventRead


class EventHub:
    def __init__(self, *, queue_size: int = 100) -> None:
        if queue_size < 1:
            raise ValueError("Размер очереди должен быть положительным")
        self.queue_size = queue_size
        self._subscribers: dict[UUID, set[Queue[EventRead]]] = {}

    @contextmanager
    def subscribe(self, shopping_list_id: UUID) -> Iterator[Queue[EventRead]]:
        queue: Queue[EventRead] = Queue(maxsize=self.queue_size)
        subscribers = self._subscribers.setdefault(shopping_list_id, set())
        subscribers.add(queue)
        try:
            yield queue
        finally:
            subscribers.remove(queue)
            if not subscribers:
                del self._subscribers[shopping_list_id]

    def publish(self, event: EventRead) -> None:
        for queue in self._subscribers.get(event.shopping_list_id, ()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event.model_copy(deep=True))


event_hub = EventHub()
