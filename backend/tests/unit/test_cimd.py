import asyncio
import json
import socket
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from grocery.config import get_settings
from grocery.services.auth import cimd
from grocery.services.auth.oauth_errors import OAuthError

URL = "https://client.example/oauth.json"


@pytest.mark.parametrize(
    "url",
    [
        "http://client.example/client.json",
        "https://127.0.0.1/client.json",
        "https://[::1]/client.json",
        "https://169.254.169.254/metadata",
        "https://user:pass@client.example/client.json",
        "https://client.example/client.json#x",
        "https://client.example",
        "https://client.example/../client.json",
        "https://client.example/%2e%2e/client.json",
    ],
)
def test_invalid_client_urls(url: str) -> None:
    with pytest.raises(OAuthError):
        cimd.validate_client_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 — address validation, not socket binding
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",
        "2002:7f00:1::",
        "64:ff9b::7f00:1",
    ],
)
def test_not_public(address: str) -> None:
    assert cimd.public_ip(address) is False


async def test_resolver_checks_every_answer_and_pins_numeric_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = cimd.PublicResolver()
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    result = await resolver.resolve("client.example", 443)
    assert result[0]["host"] == "8.8.8.8"
    assert result[0]["hostname"] == "client.example"
    assert result[0]["flags"] == socket.AI_NUMERICHOST
    lookup.return_value.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)))
    with pytest.raises(OSError, match="public addresses"):
        await resolver.resolve("client.example", 443)
    await resolver.close()


@pytest.mark.parametrize(
    ("header", "age", "expected"),
    [
        ("max-age=600", "10", 590),
        ('public, max-age="8000"', "0", 3600),
        ("no-store, max-age=600", "0", 0),
        ("no-cache", "0", 0),
        ("", "0", 300),
        ("max-age=1", "3", 0),
        ("max-age=600", "bad", 0),
    ],
)
def test_cache_ttl(header: str, age: str, expected: int) -> None:
    assert cimd.cache_seconds(header, age) == expected


def mock_fetch(monkeypatch: pytest.MonkeyPatch, body: bytes) -> MagicMock:
    async def chunks(size: int) -> AsyncIterator[bytes]:
        for offset in range(0, len(body), size):
            yield body[offset : offset + size]

    response = MagicMock(
        status=200, content_type="application/json", headers={"Cache-Control": "max-age=600"}
    )
    response.content.iter_chunked = chunks
    client = MagicMock()
    client.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=client)
    monkeypatch.setattr(aiohttp, "ClientSession", session)
    connector = MagicMock()
    monkeypatch.setattr(aiohttp, "TCPConnector", connector)
    response.test_session = session
    response.test_client = client
    response.test_connector = connector
    return response


def document(**changes: object) -> bytes:
    return json.dumps(
        {
            "client_id": URL,
            "client_name": "Client",
            "redirect_uris": ["https://client.example/cb"],
            **changes,
        }
    ).encode()


async def test_fetch_bounded_and_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    response = mock_fetch(monkeypatch, document())
    result, ttl = await cimd.fetch_document(URL)
    assert result.client_id == URL
    assert ttl == 600
    kwargs = response.test_session.call_args.kwargs
    assert kwargs["trust_env"] is False
    assert kwargs["auto_decompress"] is False
    assert response.test_client.get.call_args.kwargs["allow_redirects"] is False
    assert isinstance(response.test_connector.call_args.kwargs["resolver"], cimd.PublicResolver)


@pytest.mark.parametrize(
    "failure", ["status", "encoding", "media", "size", "invalid_json", "identity", "timeout"]
)
async def test_fetch_failures(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    body = document()
    if failure == "size":
        body = b"x" * 65537
    if failure == "invalid_json":
        body = b"invalid"
    if failure == "identity":
        body = document(client_id="https://other.example/client.json")
    response = mock_fetch(monkeypatch, body)
    if failure == "status":
        response.status = 302
    if failure == "encoding":
        response.headers["Content-Encoding"] = "gzip"
    if failure == "media":
        response.content_type = "text/html"
    if failure == "timeout":

        async def slow() -> MagicMock:
            await asyncio.sleep(1)
            return response

        response.test_client.get.return_value.__aenter__ = AsyncMock(side_effect=slow)
        get_settings().auth.cimd_timeout_seconds = 0.001
    with pytest.raises(OAuthError) as exc:
        await cimd.fetch_document(URL)
    assert exc.value.response.error == "invalid_client"
