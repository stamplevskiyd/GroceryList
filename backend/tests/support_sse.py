"""Bounded, test-only ASGI client for responses that never finish."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any
from uuid import UUID

import httpx
from starlette.types import ASGIApp, Message, Scope


class SseStream:
    def __init__(self, app: ASGIApp, request: httpx.Request, on_start: Callable[[], None]) -> None:
        self._start = asyncio.Event()
        self._incoming: asyncio.Queue[Message] = asyncio.Queue()
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = b""
        self.status = 0
        self.headers = httpx.Headers()
        self._incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "root_path": "",
            "headers": [(key.lower(), value) for key, value in request.headers.raw],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }

        async def send(message: Message) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self.headers = httpx.Headers(message["headers"])
                on_start()
                self._start.set()
            elif message["type"] == "http.response.body":
                self._chunks.put_nowait(message.get("body", b""))

        async def run() -> None:
            await app(scope, self._incoming.get, send)

        self.task = asyncio.create_task(run())

    # Explicit limits are part of this test helper's API; every wait uses asyncio.timeout.
    async def started(self, *, timeout: float = 2) -> None:  # noqa: ASYNC109
        async with asyncio.timeout(timeout):
            await self._start.wait()

    async def next_frame(self, *, timeout: float = 2) -> str:  # noqa: ASYNC109
        async with asyncio.timeout(timeout):
            while b"\n\n" not in self._buffer:
                chunk = await self._chunks.get()
                self._buffer = (self._buffer + chunk).replace(b"\r\n", b"\n")
            frame, self._buffer = self._buffer.split(b"\n\n", 1)
            return frame.decode()

    async def next_data(self, *, timeout: float = 2) -> dict[str, Any]:  # noqa: ASYNC109
        # JSON is intentionally untyped here: tests assert the actual wire contract.
        async with asyncio.timeout(timeout):
            while True:
                frame = await self.next_frame(timeout=timeout)
                data = [
                    line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
                ]
                if data:
                    parsed: object = json.loads("\n".join(data))
                    assert isinstance(parsed, dict)
                    return parsed

    async def close(self) -> None:
        self._incoming.put_nowait({"type": "http.disconnect"})
        try:
            async with asyncio.timeout(2):
                await asyncio.shield(self.task)
        finally:
            if not self.task.done():
                self.task.cancel()
                with suppress(asyncio.CancelledError):
                    async with asyncio.timeout(2):
                        await self.task


class SseClient:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @asynccontextmanager
    async def connect(
        self,
        path: str,
        *,
        shopping_list_id: UUID,
        cookies: httpx.Cookies,
        on_start: Callable[[], None] = lambda: None,
    ) -> AsyncIterator[SseStream]:
        request = httpx.Request(
            "GET",
            f"https://testserver{path}",
            params={"shopping_list_id": str(shopping_list_id)},
            cookies=cookies,
        )
        stream = SseStream(self.app, request, on_start)
        try:
            yield stream
        finally:
            await stream.close()
