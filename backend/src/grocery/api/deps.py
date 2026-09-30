"""Общие dependency REST-адаптера."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Security
from fastapi.security import APIKeyCookie
from pydantic import AfterValidator, Field

from grocery.db.session import unit_of_work
from grocery.schemas.sources import AppSource
from grocery.services import auth


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
