"""Cookie session endpoints: thin adapters over the authentication service."""

from typing import Annotated

from fastapi import APIRouter, Request, Response, Security

from grocery.api.deps import (
    AppSourceDep,
    Authenticated,
    DbUnitOfWork,
    DeviceIdDep,
    session_cookie,
)
from grocery.api.errors import ERROR_RESPONSES, PROTECTED_RESPONSES, PUBLIC_RESPONSES
from grocery.config import get_settings
from grocery.schemas.auth import LoginCreate, MeRead, RegistrationCreate
from grocery.services import auth

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[DbUnitOfWork])
protected_router = APIRouter(
    prefix="/auth", tags=["auth"], dependencies=[Authenticated], responses=PROTECTED_RESPONSES
)


def set_session_cookie(response: Response, token: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=session_cookie.model.name,
        value=token,
        max_age=get_settings().auth.session_ttl_seconds,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/register",
    status_code=201,
    responses={**PUBLIC_RESPONSES, 409: ERROR_RESPONSES[409]},
)
async def register(
    data: RegistrationCreate, request: Request, response: Response, device_id: DeviceIdDep
) -> MeRead:
    if request.client is None:
        raise RuntimeError("У запроса отсутствует адрес клиента")
    result = await auth.register(data, device_id=device_id, ip=request.client.host)
    set_session_cookie(response, result.session.token)
    return result.me


@router.post("/login", responses=PUBLIC_RESPONSES)
async def login(
    data: LoginCreate, request: Request, response: Response, device_id: DeviceIdDep
) -> MeRead:
    # A network HTTP request always has a peer; no forwarded headers are parsed here.
    if request.client is None:
        raise RuntimeError("У запроса отсутствует адрес клиента")
    result = await auth.login(data, device_id=device_id, ip=request.client.host)
    set_session_cookie(response, result.session.token)
    return result.me


@protected_router.post("/logout", status_code=204)
async def logout(
    response: Response,
    source: AppSourceDep,
    token: Annotated[str | None, Security(session_cookie)],
) -> None:
    # authenticate has already resolved this same cookie dependency.
    if token is None:
        raise auth.AuthError("Требуется вход")
    await auth.logout(token)
    response.delete_cookie(
        key=session_cookie.model.name,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
