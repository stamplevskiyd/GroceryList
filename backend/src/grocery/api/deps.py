"""Общие dependency REST-адаптера."""

from asyncio import Queue
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Security
from fastapi.security import APIKeyCookie
from pydantic import AfterValidator, Field

from grocery.db.session import unit_of_work
from grocery.schemas.events import EventRead
from grocery.schemas.sources import AppSource
from grocery.services import auth
from grocery.services import shopping_list_service as service
from grocery.services.event_hub import event_hub


async def _db_unit_of_work() -> AsyncIterator[None]:
    async with unit_of_work():
        yield


# scope="function": коммит завершается до отправки ответа — упавший коммит даёт 500,
# а не «200 OK» с потерянными данными (ADR-0004).
DbUnitOfWork = Depends(_db_unit_of_work, scope="function")

session_cookie = APIKeyCookie(
    name="__Host-gl_session", scheme_name="SessionCookie", auto_error=False
)


async def authenticate(
    token: Annotated[str | None, Security(session_cookie)],
    db: Annotated[None, DbUnitOfWork],
) -> AsyncIterator[None]:
    if token is None:
        raise auth.AuthError("Требуется вход")
    with auth.acting_as(await auth.resolve_session(token)):
        yield


Authenticated = Depends(authenticate, scope="function")


async def authorize_events(
    shopping_list_id: UUID,
    token: Annotated[str | None, Security(session_cookie)],
) -> UUID:
    """Finish authentication and list authorization before the stream starts."""
    if token is None:
        raise auth.AuthError("Требуется вход")
    async with unit_of_work():
        with auth.acting_as(await auth.resolve_session(token)):
            await service.ensure_shopping_list_access(shopping_list_id)
    return shopping_list_id


async def subscribe_events(
    shopping_list_id: Annotated[UUID, Depends(authorize_events)],
) -> AsyncIterator[Queue[EventRead]]:
    # Register before headers; the request scope retains only the queue, not a DB session.
    with event_hub.subscribe(shopping_list_id) as queue:
        yield queue


SseQueueDep = Annotated[Queue[EventRead], Depends(subscribe_events, scope="request")]

DeviceId = Annotated[str, AfterValidator(str.strip), Field(min_length=1, max_length=128)]


async def get_device_id(
    device_id: Annotated[DeviceId, Header(alias="X-Device-Id")],
) -> str:
    return device_id


DeviceIdDep = Annotated[str, Depends(get_device_id)]


async def get_app_source(
    authenticated: Annotated[None, Authenticated],
    device_id: DeviceIdDep,
) -> AppSource:
    return AppSource(device_id=device_id)


AppSourceDep = Annotated[AppSource, Depends(get_app_source)]
