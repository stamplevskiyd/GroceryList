import httpx
import httpx2
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from tests.api.test_oauth import HEADERS, issue, registration


async def test_oauth_token_calls_tools_and_revocation_is_immediate(
    app: FastAPI,
    rest: httpx.AsyncClient,
    credentials: dict[str, str],
) -> None:
    client_id = await registration(rest)
    pair = await issue(rest, client_id)
    async with (
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers={"Authorization": "Bearer " + pair["access_token"]},
        ) as http,
        Client(
            streamable_http_client("https://testserver/mcp", http_client=http), cache=None
        ) as client,
    ):
        assert len((await client.list_tools()).tools) == 6
        added = await client.call_tool("add_items", {"items": [{"name": "OAuth молоко"}]})
        assert not added.is_error
    items = (await rest.get("/api/items", params={"shopping_list_id": credentials["list"]})).json()
    assert items[0]["sources"] == [{"kind": "mcp", "client_name": "Test assistant"}]
    connections = (await rest.get("/api/oauth/connections")).json()
    assert (
        await rest.delete("/api/oauth/connections/" + connections[0]["id"], headers=HEADERS)
    ).status_code == 204
    denied = await rest.post(
        "/mcp",
        headers={"Authorization": "Bearer " + pair["access_token"]},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert denied.status_code == 401
    assert "resource_metadata" in denied.headers["www-authenticate"]
    # Existing PATs remain valid after disconnecting an OAuth client.
    accepted = await rest.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + credentials["token"],
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert accepted.status_code == 200
