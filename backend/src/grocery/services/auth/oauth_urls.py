"""Strict URL and scope checks shared by registration and authorization."""

from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

from grocery.services.auth.oauth_errors import OAuthError

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def split_url(value: str) -> SplitResult:
    try:
        if len(value) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or "\\" in value:
            raise ValueError
        parts = urlsplit(value)
        if not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError
        _ = parts.port
        return parts
    except ValueError as exc:
        raise OAuthError("invalid_request", "Некорректный URL") from exc


def validate_redirect(uri: str) -> None:
    parts = split_url(uri)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK):
        raise OAuthError("invalid_redirect_uri", "Нужен HTTPS или HTTP loopback адрес")
    if any(
        key in {"code", "state", "iss", "error", "error_description"}
        for key, _ in parse_qsl(parts.query)
    ):
        raise OAuthError("invalid_redirect_uri", "Адрес содержит параметры ответа OAuth")


def redirect_matches(candidate: str, registered: str) -> bool:
    if candidate == registered:
        return True
    a, b = split_url(candidate), split_url(registered)
    return (
        a.scheme == b.scheme == "http"
        and a.hostname == b.hostname
        and a.hostname in LOOPBACK
        and a.path == b.path
        and a.query == b.query
    )


def callback(uri: str, state: str | None, issuer: str, **values: str) -> str:
    parts = split_url(uri)
    params = [*parse_qsl(parts.query, keep_blank_values=True), *values.items(), ("iss", issuer)]
    if state is not None:
        params.append(("state", state))
    return urlunsplit(parts._replace(query=urlencode(params)))


def scopes(value: str) -> str:
    requested = set(value.split())
    if "shopping_list" not in requested or requested - {"shopping_list", "offline_access"}:
        raise OAuthError("invalid_scope", "Допустимы shopping_list и offline_access")
    return " ".join(sorted(requested))
