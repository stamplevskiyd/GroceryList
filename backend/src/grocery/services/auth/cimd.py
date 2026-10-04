"""Bounded CIMD fetch with DNS pinning at the connector boundary."""

import asyncio
import ipaddress
import re
import socket
from urllib.parse import unquote

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from pydantic import ValidationError

from grocery.config import get_settings
from grocery.schemas.oauth import ClientDocument
from grocery.services.auth.oauth_errors import OAuthError
from grocery.services.auth.oauth_urls import split_url


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    # Reject transition mechanisms that can reach an embedded private IPv4.
    if isinstance(address, ipaddress.IPv6Address) and (
        address.ipv4_mapped or address.sixtofour or address.teredo
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and (
        address in ipaddress.ip_network("64:ff9b::/96")
        or address in ipaddress.ip_network("64:ff9b:1::/48")
    ):
        return False
    return address.is_global and not address.is_multicast


class PublicResolver(AbstractResolver):
    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[ResolveResult]:
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        if not records or any(not public_ip(str(record[4][0])) for record in records):
            raise OSError("CIMD host must resolve exclusively to public addresses")
        # Numeric addresses are handed directly to the connector. TLS still verifies
        # the original hostname; DNS is not queried again when opening the socket.
        return [
            ResolveResult(
                hostname=host,
                host=str(address[0]),
                port=port,
                family=af,
                proto=proto,
                flags=socket.AI_NUMERICHOST,
            )
            for af, _, proto, _, address in records
        ]

    async def close(self) -> None:
        return None


def validate_client_url(url: str) -> None:
    parts = split_url(url)
    if (
        parts.scheme != "https"
        or not parts.path
        or any(part in {".", ".."} for part in unquote(parts.path).split("/"))
    ):
        raise OAuthError("invalid_client", "CIMD требует HTTPS URL с путём")
    try:
        address = ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        return
    if not public_ip(str(address)):
        raise OAuthError("invalid_client", "CIMD требует публичный адрес")


def cache_seconds(header: str, age: str = "0") -> int:
    directives = [part.strip().lower() for part in header.split(",")]
    if any(part.split("=", 1)[0] in {"no-store", "no-cache"} for part in directives):
        return 0
    match = re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)"?', header, re.I)
    if match is None and any(part.startswith("max-age") for part in directives):
        return 0
    ttl = min(int(match[1]), 3600) if match else 300
    try:
        return max(0, ttl - max(0, int(age)))
    except ValueError:
        return 0


async def fetch_document(url: str) -> tuple[ClientDocument, int]:
    validate_client_url(url)
    settings = get_settings().auth
    try:
        async with (
            asyncio.timeout(settings.cimd_timeout_seconds),
            aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False),
                timeout=aiohttp.ClientTimeout(total=settings.cimd_timeout_seconds),
                trust_env=False,
                auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(),
            ) as client,
            client.get(
                url,
                allow_redirects=False,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response,
        ):
            media_type = response.content_type
            if (
                response.status != 200
                or response.headers.get("Content-Encoding", "identity") != "identity"
                or not (
                    media_type == "application/json"
                    or (media_type.startswith("application/") and media_type.endswith("+json"))
                )
            ):
                raise OAuthError("invalid_client", "Не удалось получить JSON-документ CIMD")
            body = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                body.extend(chunk)
                if len(body) > settings.cimd_max_bytes:
                    raise OAuthError("invalid_client", "Документ CIMD слишком большой")
            document = ClientDocument.model_validate_json(body)
            if document.client_id != url:
                raise OAuthError("invalid_client", "client_id документа не совпадает с URL")
            return document, cache_seconds(
                response.headers.get("Cache-Control", ""), response.headers.get("Age", "0")
            )
    except (aiohttp.ClientError, OSError, TimeoutError, ValidationError) as exc:
        raise OAuthError("invalid_client", "Не удалось проверить документ CIMD") from exc
