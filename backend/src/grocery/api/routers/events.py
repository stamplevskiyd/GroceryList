"""Authorized live events; the request retains no database or ORM context."""

from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse

from grocery.api.deps import SseQueueDep
from grocery.api.errors import SSE_PROTECTED_RESPONSES
from grocery.schemas.events import ShoppingListEventRead

router = APIRouter(tags=["events"])


@router.get("/events", response_class=EventSourceResponse, responses=SSE_PROTECTED_RESPONSES)
async def events(queue: SseQueueDep) -> AsyncIterable[ShoppingListEventRead]:
    while True:
        snapshot = await queue.get()
        yield ShoppingListEventRead.model_validate(snapshot.model_dump())
