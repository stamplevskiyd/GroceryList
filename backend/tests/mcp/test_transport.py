from uuid import uuid7

import httpx
import pytest
from mcp import Client
from mcp.types import TextContent


@pytest.mark.parametrize("token", [None, "unknown", "gl_pat_unknown", "gl_at_unknown"])
async def test_http_auth(rest: httpx.AsyncClient, token: str | None) -> None:
    headers = {} if token is None else {"Authorization": "Bearer " + token}
    response = await rest.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]
    assert not response.history


async def test_metadata_and_cors(rest: httpx.AsyncClient, credentials: dict[str, str]) -> None:
    root = await rest.get("/.well-known/oauth-protected-resource")
    sdk = await rest.get("/.well-known/oauth-protected-resource/mcp")
    assert root.status_code == sdk.status_code == 200
    assert root.json() == sdk.json()
    assert root.json()["resource"] == "http://testserver/mcp"
    assert (await rest.get("/api/health")).status_code == 200
    preflight = await rest.options(
        "/mcp",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,mcp-protocol-version",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://testserver"
    refused = await rest.post(
        "/mcp",
        headers={"Host": "evil.test", "Authorization": "Bearer " + credentials["token"]},
        json={},
    )
    assert refused.status_code == 421
    refused_origin = await rest.post(
        "/mcp",
        headers={"Origin": "https://evil.test", "Authorization": "Bearer " + credentials["token"]},
        json={},
    )
    assert refused_origin.status_code == 403


async def test_tools_patch_merge_bought_delete(mcp: Client) -> None:
    async with mcp:
        listed = await mcp.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "get_shopping_list",
            "list_tags",
            "add_items",
            "update_item",
            "set_bought",
            "remove_items",
        }
        for tool in listed.tools:
            assert tool.input_schema["additionalProperties"] is False
        added = await mcp.call_tool(
            "add_items",
            {
                "items": [
                    {
                        "name": "Молоко",
                        "quantity": 1,
                        "unit": "л",
                        "tags": ["Завтрак"],
                        "note": "first",
                    }
                ]
            },
        )
        assert not added.is_error
        assert added.structured_content is not None
        item = added.structured_content["result"][0]["item"]
        id = item["id"]
        assert item["quantity"] == 1000
        merged = await mcp.call_tool(
            "add_items", {"items": [{"name": "молоко", "quantity": 500, "unit": "мл"}]}
        )
        assert merged.structured_content is not None
        assert merged.structured_content["result"][0]["status"] == "merged"
        patched = await mcp.call_tool("update_item", {"id": id, "note": None})
        assert patched.structured_content is not None
        assert patched.structured_content["quantity"] == 1500
        assert patched.structured_content["note"] is None
        assert patched.structured_content["tags"][0]["name"] == "Завтрак"
        cleared = await mcp.call_tool("update_item", {"id": id, "quantity": None, "tags": []})
        assert cleared.structured_content is not None
        assert cleared.structured_content["quantity"] is None
        assert cleared.structured_content["tags"] == []
        for tool_name, args in [("get_shopping_list", {"tag": "Завтрак"}), ("list_tags", {})]:
            assert not (await mcp.call_tool(tool_name, args)).is_error
        for bought in [True, True, False]:
            assert not (await mcp.call_tool("set_bought", {"ids": [id], "bought": bought})).is_error
        removed = await mcp.call_tool("remove_items", {"ids": [id]})
        assert removed.structured_content == {"count": 1}
        missing = await mcp.call_tool("update_item", {"id": id, "note": "new"})
        assert missing.is_error
        assert isinstance(missing.content[0], TextContent)
        assert "get_shopping_list" in missing.content[0].text


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("add_items", {"items": []}),
        ("add_items", {"items": [{"name": "Молоко"}], "source": {"kind": "app"}}),
        ("remove_items", {}),
        ("remove_items", {"ids": []}),
        ("remove_items", {"ids": [str(uuid7())], "tag": "Recipe"}),
        ("set_bought", {"ids": [], "bought": True}),
        ("update_item", {"id": str(uuid7()), "name": None}),
        ("update_item", {"id": str(uuid7()), "tags": None}),
    ],
)
async def test_invalid_arguments(mcp: Client, tool: str, args: dict[str, object]) -> None:
    async with mcp:
        assert (await mcp.call_tool(tool, args)).is_error
        current = await mcp.call_tool("get_shopping_list", {})
        assert current.structured_content == {"result": []}


async def test_revoke_between_requests(
    mcp: Client, rest: httpx.AsyncClient, credentials: dict[str, str]
) -> None:
    async with mcp:
        assert not (await mcp.call_tool("get_shopping_list", {})).is_error
        assert (
            await rest.delete("/api/tokens/" + credentials["id"], headers={"X-Device-Id": "phone"})
        ).status_code == 204
        response = await rest.post(
            "/mcp",
            headers={"Authorization": "Bearer " + credentials["token"]},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 401


async def test_legacy_handshake(mcp: Client) -> None:
    mcp.mode = "legacy"
    async with mcp:
        assert len((await mcp.list_tools()).tools) == 6
        assert not (await mcp.call_tool("get_shopping_list", {})).is_error


async def test_cookie_does_not_authorize_mcp(
    rest: httpx.AsyncClient, credentials: dict[str, str]
) -> None:
    assert rest.cookies
    response = await rest.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


@pytest.mark.parametrize("invalid", ["resource", "scope"])
async def test_sdk_rejects_wrong_resource_or_scope(
    rest: httpx.AsyncClient,
    credentials: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    from mcp.server.auth.provider import AccessToken

    from grocery.mcp_server.verifier import GroceryTokenVerifier

    original = GroceryTokenVerifier.verify_token

    async def invalid_identity(verifier: GroceryTokenVerifier, raw: str) -> AccessToken | None:
        token = await original(verifier, raw)
        assert token is not None
        if invalid == "resource":
            token.resource = "https://other.example/mcp"
        else:
            token.scopes = []
        return token

    monkeypatch.setattr(GroceryTokenVerifier, "verify_token", invalid_identity)
    response = await rest.post(
        "/mcp",
        headers={"Authorization": "Bearer " + credentials["token"]},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code in (401, 403)
