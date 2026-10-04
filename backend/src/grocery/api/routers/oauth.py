"""OAuth protocol adapters and cookie-protected consent/connection endpoints."""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ValidationError

from grocery.api.deps import AppSourceDep, Authenticated
from grocery.api.errors import PROTECTED_RESPONSES
from grocery.config import get_settings
from grocery.db.session import unit_of_work
from grocery.schemas.oauth import (
    AuthorizationParams,
    AuthorizationStarted,
    ClientMetadata,
    ClientRegistered,
    ConnectionRead,
    ConsentCreate,
    ConsentRead,
    OAuthFailure,
    OAuthMetadata,
    OAuthTokenRead,
    RedirectRead,
    RevokeRequest,
    TokenRequest,
)
from grocery.services.auth import oauth as service
from grocery.services.auth.errors import TooManyAttemptsError
from grocery.services.auth.oauth_errors import OAuthError
from grocery.services.auth.rate_limit import LoginLimiter

PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Access-Control-Allow-Origin": "*",
}
BROWSER_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
router = APIRouter(tags=["oauth"], responses={400: {"model": OAuthFailure}})
protected_router = APIRouter(
    prefix="/oauth",
    tags=["oauth"],
    dependencies=[Authenticated],
    responses={**PROTECTED_RESPONSES, 400: {"model": OAuthFailure}},
)


def body_schema(model: type[BaseModel], media: str) -> dict[str, object]:
    return {
        "requestBody": {"required": True, "content": {media: {"schema": model.model_json_schema()}}}
    }


@lru_cache
def public_limiter() -> LoginLimiter:
    # Bound anonymous registration and outbound CIMD requests in our single worker.
    return LoginLimiter(username_limit=300, ip_limit=60, window_seconds=60)


def reserve(request: Request) -> None:
    try:
        public_limiter().reserve(
            username=request.url.path, ip=request.client.host if request.client else "unknown"
        )
    except TooManyAttemptsError as exc:
        raise OAuthError(
            "temporarily_unavailable", "Слишком много запросов; повторите через минуту"
        ) from exc


async def read_model[T: BaseModel](
    request: Request, model: type[T], media: Literal["json", "form"]
) -> T:
    expected = "application/json" if media == "json" else "application/x-www-form-urlencoded"
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != expected:
        raise OAuthError("invalid_request", f"Требуется {expected}")
    if request.headers.get("authorization"):
        raise OAuthError(
            "invalid_client", "Поддерживаются только публичные клиенты без client_secret"
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise OAuthError("invalid_request", "Запрос слишком большой")
    try:
        if media == "json":
            return model.model_validate_json(body)
        pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, max_num_fields=30)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("Duplicate parameters")
        if any(key == "client_secret" for key, _ in pairs):
            raise OAuthError("invalid_client", "client_secret не поддерживается")
        return model.model_validate(dict(pairs))
    except (ValidationError, ValueError, UnicodeError) as exc:
        raise OAuthError("invalid_request", "Некорректные параметры OAuth") from exc


def browser_cookie(id: UUID) -> str:
    return f"__Host-gl_oauth_{id}"


@router.get("/.well-known/oauth-authorization-server", response_model=OAuthMetadata)
async def metadata(response: Response) -> OAuthMetadata:
    response.headers.update(PUBLIC_HEADERS)
    origin = get_settings().app.origin
    return OAuthMetadata(
        issuer=origin,
        authorization_endpoint=origin + "/oauth/authorize",
        token_endpoint=origin + "/oauth/token",
        registration_endpoint=origin + "/oauth/register",
        revocation_endpoint=origin + "/oauth/revoke",
    )


@router.options("/oauth/register", include_in_schema=False)
@router.options("/oauth/token", include_in_schema=False)
@router.options("/oauth/revoke", include_in_schema=False)
@router.options("/.well-known/oauth-authorization-server", include_in_schema=False)
async def preflight() -> Response:
    return Response(
        status_code=204,
        headers={
            **PUBLIC_HEADERS,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


@router.post(
    "/oauth/register",
    status_code=201,
    response_model=ClientRegistered,
    openapi_extra=body_schema(ClientMetadata, "application/json"),
)
async def register(request: Request) -> JSONResponse:
    reserve(request)
    data = await read_model(request, ClientMetadata, "json")
    async with unit_of_work():
        result = await service.register(data)
    return JSONResponse(result.model_dump(mode="json"), status_code=201, headers=PUBLIC_HEADERS)


@router.get(
    "/oauth/authorize",
    response_class=RedirectResponse,
    status_code=303,
    openapi_extra={
        "parameters": [
            {
                "name": name,
                "in": "query",
                "required": name in AuthorizationParams.model_json_schema().get("required", []),
                "schema": schema,
            }
            for name, schema in AuthorizationParams.model_json_schema()["properties"].items()
        ]
    },
)
async def authorize(request: Request) -> Response:
    reserve(request)
    try:
        if len(str(request.url.query)) > 8192 or len(set(request.query_params)) != len(
            request.query_params.multi_items()
        ):
            raise ValueError("Duplicate/oversized parameters")
        params = AuthorizationParams.model_validate(dict(request.query_params))
    except (ValidationError, ValueError) as exc:
        raise OAuthError("invalid_request", "Некорректный запрос авторизации") from exc
    async with unit_of_work():
        result = await service.authorize(params)
    if not isinstance(result, AuthorizationStarted):
        return RedirectResponse(result.redirect_url, status_code=303, headers=BROWSER_HEADERS)
    response = RedirectResponse(
        f"/consent?request={result.request_id}", status_code=303, headers=BROWSER_HEADERS
    )
    response.set_cookie(
        browser_cookie(result.request_id),
        result.browser_token,
        max_age=get_settings().auth.oauth_request_ttl_seconds,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post(
    "/oauth/token",
    response_model=OAuthTokenRead,
    openapi_extra=body_schema(TokenRequest, "application/x-www-form-urlencoded"),
)
async def token(request: Request) -> JSONResponse:
    reserve(request)
    data = await read_model(request, TokenRequest, "form")
    async with unit_of_work():
        result = await service.exchange(data)
    # Security mutations (replay -> family revocation) committed before returning 400.
    return JSONResponse(
        result.model_dump(mode="json", exclude_none=True),
        status_code=400 if isinstance(result, OAuthFailure) else 200,
        headers=PUBLIC_HEADERS,
    )


@router.post(
    "/oauth/revoke",
    status_code=200,
    openapi_extra=body_schema(RevokeRequest, "application/x-www-form-urlencoded"),
)
async def revoke(request: Request) -> Response:
    reserve(request)
    data = await read_model(request, RevokeRequest, "form")
    async with unit_of_work():
        await service.revoke(data)
    return Response(status_code=200, headers=PUBLIC_HEADERS)


@protected_router.get("/requests/{id}", response_model=ConsentRead)
async def consent_info(id: UUID, request: Request, response: Response) -> ConsentRead:
    response.headers.update(BROWSER_HEADERS)
    return await service.consent_info(id, request.cookies.get(browser_cookie(id)))


@protected_router.post("/consent", response_model=RedirectRead)
async def consent(
    data: ConsentCreate, source: AppSourceDep, request: Request, response: Response
) -> RedirectRead:
    result = await service.consent(
        data.request_id, data.allow, request.cookies.get(browser_cookie(data.request_id))
    )
    response.headers.update(BROWSER_HEADERS)
    response.delete_cookie(
        browser_cookie(data.request_id), secure=True, httponly=True, samesite="lax", path="/"
    )
    return result


@protected_router.get("/connections", response_model=list[ConnectionRead])
async def connections(response: Response) -> list[ConnectionRead]:
    response.headers.update(BROWSER_HEADERS)
    return await service.connections()


@protected_router.delete("/connections/{id}", status_code=204)
async def disconnect(id: UUID, source: AppSourceDep) -> Response:
    await service.disconnect(id)
    return Response(status_code=204, headers=BROWSER_HEADERS)
