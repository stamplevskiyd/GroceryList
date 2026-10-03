import asyncio
import socket

import httpx2
import pytest
import uvicorn
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


@pytest.mark.real_commits
async def test_sdk_over_real_http_socket(app: FastAPI, credentials: dict[str, str]) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        listener.setblocking(False)
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        pytest.fail("Uvicorn stopped before startup")
                    await asyncio.sleep(0.01)
            async with (
                httpx2.AsyncClient(
                    headers={
                        "Authorization": "Bearer " + credentials["token"],
                        "Host": "testserver",
                    }
                ) as http,
                Client(
                    streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http),
                    cache=None,
                ) as client,
            ):
                assert len((await client.list_tools()).tools) == 6
                added = await client.call_tool("add_items", {"items": [{"name": "Лук"}]})
                assert not added.is_error
                fetched = await client.call_tool("get_shopping_list", {})
                assert fetched.structured_content is not None
                assert fetched.structured_content["result"][0]["name"] == "Лук"
        finally:
            server.should_exit = True
            async with asyncio.timeout(10):
                await task
