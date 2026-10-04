"""OAuth authorization, consent and token lifecycle (ADR-0010)."""

import base64
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr

from grocery.config import get_settings
from grocery.db.models.oauth import OAuthAuthorizationRequest, OAuthClient, OAuthGrant
from grocery.db.repositories.oauth import (
    authorization_repo,
    client_repo,
    code_repo,
    grant_repo,
    oauth_token_repo,
)
from grocery.db.session import get_current_session
from grocery.domain.enums import ClientRegistration
from grocery.domain.errors import NotFoundError
from grocery.schemas.oauth import (
    AuthorizationParams,
    AuthorizationStarted,
    AuthorizationStored,
    ClientMetadata,
    ClientRegistered,
    ClientStored,
    CodeStored,
    ConnectionRead,
    ConsentRead,
    GrantStored,
    OAuthFailure,
    OAuthTokenRead,
    OAuthTokenStored,
    RedirectRead,
    RevokeRequest,
    TokenRequest,
)
from grocery.schemas.tokens import BearerIdentity
from grocery.services.auth import cimd
from grocery.services.auth.context import get_current_user
from grocery.services.auth.oauth_errors import OAuthError
from grocery.services.auth.oauth_urls import (
    LOOPBACK,
    callback,
    redirect_matches,
    scopes,
    split_url,
    validate_redirect,
)
from grocery.services.auth.sessions import token_hash


def now() -> datetime:
    return datetime.now(UTC)


def validate_metadata(data: ClientMetadata) -> None:
    if (
        not data.client_name.strip()
        or "authorization_code" not in data.grant_types
        or data.response_types != ["code"]
    ):
        raise OAuthError("invalid_client_metadata", "Нужны имя клиента и authorization_code/code")
    for uri in data.redirect_uris:
        validate_redirect(uri)


async def register(data: ClientMetadata) -> ClientRegistered:
    validate_metadata(data)
    client = await client_repo.add(
        ClientStored(
            client_id="gl_client_" + secrets.token_urlsafe(24),
            client_metadata=data,
            registration_type=ClientRegistration.DCR,
        )
    )
    return ClientRegistered(
        **data.model_dump(),
        client_id=client.client_id,
        client_id_issued_at=int(client.created_at.timestamp()),
    )


async def resolve_client(client_id: str) -> OAuthClient:
    if not client_id.startswith("https://"):
        client = await client_repo.by_client_id(client_id)
        if client is None or client.registration_type != ClientRegistration.DCR:
            raise OAuthError("invalid_client", "Клиент не зарегистрирован")
        return client
    await client_repo.lock_identity(client_id)
    client = await client_repo.by_client_id(client_id)
    if (
        client is not None
        and client.cache_expires_at is not None
        and client.cache_expires_at > now()
    ):
        return client
    document, ttl = await cimd.fetch_document(client_id)
    metadata = ClientMetadata.model_validate(document.model_dump())
    validate_metadata(metadata)
    expires = now() + timedelta(seconds=ttl)
    if client is None:
        return await client_repo.add(
            ClientStored(
                client_id=client_id,
                client_metadata=metadata,
                registration_type=ClientRegistration.CIMD,
                cache_expires_at=expires,
            )
        )
    client.client_metadata = metadata
    client.cache_expires_at = expires
    await get_current_session().flush()
    return client


async def authorize(params: AuthorizationParams) -> AuthorizationStarted | RedirectRead:
    client = await resolve_client(params.client_id)
    validate_redirect(params.redirect_uri)
    if not any(
        redirect_matches(params.redirect_uri, uri) for uri in client.client_metadata.redirect_uris
    ):
        # Never redirect errors to an unregistered address.
        raise OAuthError("invalid_request", "Адрес возврата не зарегистрирован")
    try:
        if params.response_type != "code":
            raise OAuthError("unsupported_response_type", "Поддерживается только code")
        if params.code_challenge_method != "S256" or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", params.code_challenge
        ):
            raise OAuthError("invalid_request", "Требуется PKCE S256")
        if params.resource != get_settings().app.mcp_url:
            raise OAuthError("invalid_target", "Неверный resource")
        params.scope = scopes(params.scope)
        if (
            "offline_access" in params.scope.split()
            and "refresh_token" not in client.client_metadata.grant_types
        ):
            raise OAuthError("invalid_scope", "Клиент не зарегистрирован для refresh_token")
    except OAuthError as exc:
        return RedirectRead(
            redirect_url=callback(
                params.redirect_uri,
                params.state,
                get_settings().app.origin,
                **exc.response.model_dump(),
            )
        )
    raw = secrets.token_urlsafe(32)
    request = await authorization_repo.add(
        AuthorizationStored(
            client_pk=client.id,
            params=params,
            browser_token_hash=token_hash(raw),
            expires_at=now() + timedelta(seconds=get_settings().auth.oauth_request_ttl_seconds),
        )
    )
    return AuthorizationStarted(request_id=request.id, browser_token=raw)


async def pending(id: UUID, browser_token: str | None) -> OAuthAuthorizationRequest:
    request = await authorization_repo.locked(id)
    if (
        request is None
        or request.expires_at <= now()
        or request.consumed_at is not None
        or browser_token is None
        or not secrets.compare_digest(request.browser_token_hash, token_hash(browser_token))
    ):
        raise OAuthError(
            "invalid_request",
            "Запрос истёк или открыт в другом браузере; начните подключение заново",
        )
    user_id = get_current_user().id
    if request.user_id is not None and request.user_id != user_id:
        raise OAuthError("access_denied", "Запрос принадлежит другому пользователю")
    request.user_id = user_id
    await get_current_session().flush()
    return request


async def consent_info(id: UUID, browser_token: str | None) -> ConsentRead:
    request = await pending(id, browser_token)
    client = await client_repo.get(request.client_pk)
    if client is None:
        raise OAuthError("invalid_client", "Клиент не найден")
    host = split_url(request.params.redirect_uri).hostname or ""
    return ConsentRead(
        request_id=id,
        client_name=client.client_metadata.client_name,
        redirect_uri=request.params.redirect_uri,
        redirect_host=host,
        loopback=host in LOOPBACK,
        scopes=request.params.scope.split(),
        expires_at=request.expires_at,
    )


async def consent(id: UUID, allow: bool, browser_token: str | None) -> RedirectRead:
    request = await pending(id, browser_token)
    params = request.params
    instant = now()
    request.consumed_at = instant
    if not allow:
        await get_current_session().flush()
        return RedirectRead(
            redirect_url=callback(
                params.redirect_uri,
                params.state,
                get_settings().app.origin,
                error="access_denied",
                error_description="Пользователь отклонил доступ",
            )
        )
    await grant_repo.lock_user(get_current_user().id)
    settings = get_settings().auth
    ttl = (
        settings.oauth_refresh_ttl_seconds
        if "offline_access" in params.scope.split()
        else settings.oauth_access_ttl_seconds
    )
    grant = await grant_repo.add(
        GrantStored(
            client_pk=request.client_pk,
            user_id=get_current_user().id,
            scope=params.scope,
            resource=params.resource,
            expires_at=instant + timedelta(seconds=ttl),
        )
    )
    raw = "gl_code_" + secrets.token_urlsafe(32)
    await code_repo.add(
        CodeStored(
            token_hash=token_hash(raw),
            family_id=grant.id,
            redirect_uri=params.redirect_uri,
            code_challenge=params.code_challenge,
            expires_at=instant + timedelta(seconds=settings.oauth_code_ttl_seconds),
        )
    )
    return RedirectRead(
        redirect_url=callback(
            params.redirect_uri, params.state, get_settings().app.origin, code=raw
        )
    )


def invalid_grant() -> OAuthFailure:
    return OAuthFailure(
        error="invalid_grant", error_description="Код или токен недействителен; подключитесь заново"
    )


async def issue_pair(grant: OAuthGrant) -> OAuthTokenRead:
    instant = now()
    ttl = min(
        get_settings().auth.oauth_access_ttl_seconds,
        int((grant.expires_at - instant).total_seconds()),
    )
    if ttl <= 0:
        raise OAuthError("invalid_grant", "Разрешение истекло")
    access = "gl_at_" + secrets.token_urlsafe(32)
    refresh = (
        "gl_rt_" + secrets.token_urlsafe(32) if "offline_access" in grant.scope.split() else None
    )
    await oauth_token_repo.add(
        OAuthTokenStored(
            family_id=grant.id,
            access_token_hash=token_hash(access),
            refresh_token_hash=token_hash(refresh) if refresh else None,
            expires_at=instant + timedelta(seconds=ttl),
        )
    )
    return OAuthTokenRead(
        access_token=SecretStr(access),
        refresh_token=SecretStr(refresh) if refresh else None,
        expires_in=ttl,
        scope=grant.scope,
    )


async def bound_grant(id: UUID, data: TokenRequest) -> OAuthGrant | None:
    grant = await grant_repo.locked(id)
    if grant is None or grant.revoked_at is not None or grant.expires_at <= now():
        return None
    client = await client_repo.get(grant.client_pk)
    if client is None or client.client_id != data.client_id or grant.resource != data.resource:
        return None
    return grant


async def exchange(data: TokenRequest) -> OAuthTokenRead | OAuthFailure:
    if data.resource != get_settings().app.mcp_url:
        return OAuthFailure(error="invalid_target", error_description="Неверный resource")
    if data.grant_type == "authorization_code":
        code = await code_repo.by_hash(token_hash(data.code))
        if code is None or code.expires_at <= now() or code.redirect_uri != data.redirect_uri:
            return invalid_grant()
        if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", data.code_verifier):
            return invalid_grant()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(data.code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        if not secrets.compare_digest(challenge, code.code_challenge):
            return invalid_grant()
        grant = await bound_grant(code.family_id, data)
        if grant is None:
            return invalid_grant()
        if code.consumed_at is not None:
            grant.revoked_at = now()
            await get_current_session().flush()
            return invalid_grant()
        code.consumed_at = now()
        return await issue_pair(grant)
    if data.grant_type == "refresh_token":
        token = await oauth_token_repo.by_hash(token_hash(data.refresh_token), refresh=True)
        if token is None:
            return invalid_grant()
        grant = await bound_grant(token.family_id, data)
        if grant is None:
            return invalid_grant()
        # Re-read after the family lock: a concurrent refresh may have rotated it.
        token = await oauth_token_repo.by_hash(token_hash(data.refresh_token), refresh=True)
        if token is None:
            return invalid_grant()
        if data.scope is not None and scopes(data.scope) != grant.scope:
            raise OAuthError("invalid_scope", "Изменение scope требует нового согласия")
        instant = now()
        if (
            token.rotated_at is not None
            and (instant - token.rotated_at).total_seconds()
            > get_settings().auth.oauth_refresh_grace_seconds
        ):
            grant.revoked_at = instant
            await get_current_session().flush()
            # Return, don't raise: the protective revocation must be committed.
            return invalid_grant()
        if token.rotated_at is None:
            token.rotated_at = instant
        return await issue_pair(grant)
    return OAuthFailure(
        error="unsupported_grant_type",
        error_description="Нужен authorization_code или refresh_token",
    )


async def revoke(data: RevokeRequest) -> None:
    is_refresh = data.token.startswith("gl_rt_")
    token = await oauth_token_repo.by_hash(token_hash(data.token), refresh=is_refresh)
    if token is None:
        return
    grant = await grant_repo.locked(token.family_id)
    if grant is None:
        return
    client = await client_repo.get(grant.client_pk)
    if client is None or client.client_id != data.client_id:
        return
    if is_refresh:
        grant.revoked_at = now()
    else:
        token.revoked_at = now()
    await get_current_session().flush()


async def verify_access(raw: str) -> BearerIdentity | None:
    if not raw.startswith("gl_at_"):
        return None
    token = await oauth_token_repo.by_hash(token_hash(raw))
    if token is None or token.revoked_at is not None or token.expires_at <= now():
        return None
    grant = await grant_repo.get(token.family_id)
    if (
        grant is None
        or grant.revoked_at is not None
        or grant.expires_at <= now()
        or grant.resource != get_settings().app.mcp_url
    ):
        return None
    client = await client_repo.get(grant.client_pk)
    if client is None:
        return None
    return BearerIdentity(
        user_id=grant.user_id,
        client_id=client.client_id,
        client_name=client.client_metadata.client_name,
        scopes=grant.scope.split(),
        resource=grant.resource,
    )


async def connections() -> list[ConnectionRead]:
    result: dict[UUID, ConnectionRead] = {}
    for grant in await grant_repo.for_user(get_current_user().id):
        if grant.revoked_at is not None or grant.expires_at <= now():
            continue
        client = await client_repo.get(grant.client_pk)
        if client is None:
            continue
        previous = result.get(client.id)
        result[client.id] = ConnectionRead(
            id=client.id,
            client_id=client.client_id,
            client_name=client.client_metadata.client_name,
            connected_at=min(previous.connected_at, grant.created_at)
            if previous
            else grant.created_at,
            scopes=sorted(set(grant.scope.split()) | set(previous.scopes if previous else [])),
        )
    return list(result.values())


async def disconnect(client_pk: UUID) -> None:
    user_id = get_current_user().id
    await grant_repo.lock_user(user_id)
    grants = await grant_repo.for_user(user_id, client_pk)
    if not grants:
        raise NotFoundError("Подключение не найдено")
    for grant in grants:
        if grant.revoked_at is None:
            grant.revoked_at = now()
    await get_current_session().flush()
