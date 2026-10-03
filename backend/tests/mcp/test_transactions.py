import asyncio
from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.types import TextContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grocery.db.models import Event, Item, PersonalAccessToken
from grocery.db.session import get_current_session, unit_of_work
from grocery.domain.errors import InvalidInputError
from grocery.schemas.items import AddItemResult, AddItems
from grocery.schemas.sources import McpSource, Source
from grocery.services import shopping_list_service as service
from grocery.services.auth import AuthError, get_current_user
from grocery.services.event_hub import event_hub
from tests.support_sse import SseClient


@pytest.mark.real_commits
async def test_mcp_commit_visible_via_rest_and_sse(
    mcp: Client, rest: httpx.AsyncClient, app: FastAPI, credentials: dict[str, str]
) -> None:
    list_id = UUID(credentials["list"])
    async with (
        mcp,
        SseClient(app).connect(
            "/api/events", shopping_list_id=list_id, cookies=rest.cookies
        ) as stream,
    ):
        await stream.started()
        with event_hub.subscribe(uuid7()) as other:
            result = await mcp.call_tool(
                "add_items", {"items": [{"name": "Лук"}, {"name": "Морковь"}]}
            )
            assert not result.is_error
            data = await stream.next_data()
            assert data["type"] == "items_added"
            assert len(data["payload"]["results"]) == 2
            assert other.empty()
        persisted = (
            await rest.get("/api/items", params={"shopping_list_id": credentials["list"]})
        ).json()
        assert len(persisted) == 2
        assert persisted[0]["sources"] == [{"kind": "mcp", "client_name": "Test assistant"}]
    async with unit_of_work() as db:
        events = list(await db.scalars(select(Event)))
        assert len(events) == 1
        assert events[0].source.kind == "mcp"
        assert events[0].source.client_id == credentials["id"]
    with pytest.raises(AuthError):
        get_current_user()
    with pytest.raises(RuntimeError):
        get_current_session()


@pytest.mark.real_commits
@pytest.mark.parametrize("failure", ["domain", "unexpected", "commit"])
async def test_failed_tool_rolls_back_writes_and_events(
    mcp: Client, credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original = service.add_items
    original_commit = AsyncSession.commit

    async def add_then_fail(data: AddItems, source: Source) -> list[AddItemResult]:
        result = await original(data, source)
        if failure == "commit":
            get_current_session().info["fail_commit"] = True
            return result
        if failure == "domain":
            raise InvalidInputError("Пакет отклонён")
        raise RuntimeError("PRIVATE_DATABASE_DETAIL")

    async def commit(session: AsyncSession) -> None:
        if session.info.get("fail_commit"):
            raise RuntimeError("PRIVATE_COMMIT_DETAIL")
        await original_commit(session)

    monkeypatch.setattr(service, "add_items", add_then_fail)
    monkeypatch.setattr(AsyncSession, "commit", commit)
    async with mcp:
        with event_hub.subscribe(UUID(credentials["list"])) as queue:
            result = await mcp.call_tool("add_items", {"items": [{"name": "Лук"}]})
            assert result.is_error
            assert isinstance(result.content[0], TextContent)
            assert "PRIVATE" not in result.content[0].text
            assert queue.empty()
        async with unit_of_work() as db:
            assert list(await db.scalars(select(Item))) == []
            assert list(await db.scalars(select(Event))) == []
            stored_token = await db.get(PersonalAccessToken, UUID(credentials["id"]))
            assert stored_token is not None
            assert stored_token.last_used_at is not None


@pytest.mark.real_commits
async def test_cancellation_rolls_back(
    credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from mcp.server import ServerRequestContext
    from mcp.server.auth.provider import AccessToken
    from mcp.server.context import HandlerResult
    from mcp.server.session import ServerSession

    from grocery.mcp_server import middleware
    from grocery.schemas.items import ItemCreate
    from grocery.schemas.sources import McpSource

    async with unit_of_work() as db:
        event = await db.scalar(select(Event))
        assert event is None
    # Resolve the actual owner through the PAT verifier, not a test-only identity.
    from grocery.mcp_server.verifier import GroceryTokenVerifier

    token = await GroceryTokenVerifier().verify_token(credentials["token"])
    assert isinstance(token, AccessToken)
    monkeypatch.setattr(middleware, "get_access_token", lambda: token)
    ctx: ServerRequestContext = ServerRequestContext(
        session=Mock(spec=ServerSession),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
    )

    async def cancelled(ctx: ServerRequestContext) -> HandlerResult:
        await service.add_items(
            AddItems(shopping_list_id=UUID(credentials["list"]), items=[ItemCreate(name="Лук")]),
            McpSource(client_id=credentials["id"], client_name="Test assistant"),
        )
        raise asyncio.CancelledError

    with event_hub.subscribe(UUID(credentials["list"])) as queue:
        with pytest.raises(asyncio.CancelledError):
            await middleware.tool_unit_of_work(ctx, cancelled)
        assert queue.empty()
    async with unit_of_work() as db:
        assert list(await db.scalars(select(Item))) == []


async def test_list_selection_and_foreign_objects(mcp: Client, credentials: dict[str, str]) -> None:
    from grocery.db.repositories.shopping import member_repo, shopping_list_repo
    from grocery.domain.enums import MemberRole
    from grocery.mcp_server.verifier import GroceryTokenVerifier
    from grocery.schemas.items import ItemCreate
    from grocery.schemas.shopping_lists import MemberCreate, ShoppingListCreate
    from grocery.schemas.sources import AppSource
    from grocery.services.auth import acting_as, create_user
    from grocery.services.auth.tokens import resolve_bearer_user

    token = await GroceryTokenVerifier().verify_token(credentials["token"])
    assert token is not None
    assert token.subject is not None
    async with unit_of_work():
        owner = await resolve_bearer_user(UUID(token.subject))
        second = await shopping_list_repo.add(ShoppingListCreate(name="Другой", owner_id=owner.id))
        await member_repo.add(
            MemberCreate(shopping_list_id=second.id, user_id=owner.id, role=MemberRole.OWNER)
        )
        other = await create_user("boris", "password")
        with acting_as(other):
            foreign_list = await service.get_default_shopping_list_id()
            foreign_item = (
                await service.add_items(
                    AddItems(shopping_list_id=foreign_list, items=[ItemCreate(name="Чай")]),
                    AppSource(device_id="boris"),
                )
            )[0].item.id
    async with mcp:
        assert (await mcp.call_tool("get_shopping_list", {})).is_error
        created = await mcp.call_tool(
            "add_items",
            {
                "shopping_list_id": credentials["list"],
                "items": [{"name": "Лук", "tags": ["Для супа"]}],
            },
        )
        assert created.structured_content is not None
        item_id = created.structured_content["result"][0]["item"]["id"]
        wrong = await mcp.call_tool(
            "update_item", {"shopping_list_id": str(second.id), "id": item_id, "note": "wrong"}
        )
        assert wrong.is_error
        assert isinstance(wrong.content[0], TextContent)
        assert "get_shopping_list" in wrong.content[0].text
        found = await mcp.call_tool(
            "get_shopping_list", {"shopping_list_id": credentials["list"], "tag": "для СУПА"}
        )
        assert found.structured_content is not None
        assert len(found.structured_content["result"]) == 1
        cases: list[tuple[str, dict[str, object]]] = [
            ("get_shopping_list", {}),
            ("list_tags", {}),
            ("add_items", {"items": [{"name": "Чай"}]}),
            ("update_item", {"id": str(foreign_item), "note": "wrong"}),
            ("set_bought", {"ids": [str(foreign_item)], "bought": True}),
            ("remove_items", {"ids": [str(foreign_item)]}),
        ]
        for tool, args in cases:
            assert (
                await mcp.call_tool(tool, {"shopping_list_id": str(foreign_list), **args})
            ).is_error


@pytest.mark.real_commits
async def test_concurrent_users_keep_identity_and_transactions_separate(
    app: FastAPI, credentials: dict[str, str]
) -> None:
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    from grocery.schemas.tokens import TokenCreate
    from grocery.services.auth import acting_as, create_user
    from grocery.services.auth.tokens import issue_token

    async with unit_of_work():
        other = await create_user("boris", "password")
        with acting_as(other):
            other_list = await service.get_default_shopping_list_id()
            other_token = await issue_token(TokenCreate(name="Boris assistant"))

    async def add(raw: str, name: str) -> None:
        async with (
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), headers={"Authorization": "Bearer " + raw}
            ) as http,
            Client(
                streamable_http_client("https://testserver/mcp", http_client=http), cache=None
            ) as client,
        ):
            result = await client.call_tool("add_items", {"items": [{"name": name}]})
            assert not result.is_error

    await asyncio.gather(
        add(credentials["token"], "Лук"), add(other_token.token.get_secret_value(), "Чай")
    )
    async with unit_of_work() as db:
        items = list(await db.scalars(select(Item)))
        assert {item.shopping_list_id: item.name for item in items} == {
            UUID(credentials["list"]): "Лук",
            other_list: "Чай",
        }
        events = list(await db.scalars(select(Event)))
        sources = [event.source for event in events]
        assert all(isinstance(source, McpSource) for source in sources)
        assert {source.client_name for source in sources if isinstance(source, McpSource)} == {
            "Test assistant",
            "Boris assistant",
        }
        assert len(events) == 2
        other_event = next(event for event in events if event.shopping_list_id == other_list)
        assert other_event.user_id == other.id
        assert isinstance(other_event.source, McpSource)
        assert other_event.source.client_id == str(other_token.id)
        owner_event = next(
            event for event in events if event.shopping_list_id == UUID(credentials["list"])
        )
        assert owner_event.user_id != other.id
        assert isinstance(owner_event.source, McpSource)
        assert owner_event.source.client_id == credentials["id"]
    with pytest.raises(AuthError):
        get_current_user()
