"""SSE authorization precedes headers; live streams hold queues, never database sessions."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from grocery.db.models import Event
from grocery.db.repositories.sessions import session_repo
from grocery.db.session import override_session_factory, unit_of_work
from grocery.domain.enums import EventType
from grocery.schemas.events import EventPayload, EventRead
from grocery.schemas.items import AddItems, ItemCreate, ItemRead
from grocery.schemas.sources import AppSource
from grocery.services import auth
from grocery.services import shopping_list_service as service
from grocery.services.auth.sessions import token_hash
from grocery.services.event_hub import event_hub
from tests.support_sse import SseClient

COOKIE = "__Host-gl_session"


@pytest.fixture
def sse_client(app: FastAPI) -> SseClient:
    return SseClient(app)


@dataclass
class SessionCounter:
    opened: int = 0
    active: int = 0


@pytest.fixture
def session_counter(engine: AsyncEngine) -> Iterator[SessionCounter]:
    counter = SessionCounter()

    class CountedSession(AsyncSession):
        async def __aenter__(self) -> Self:
            result = await super().__aenter__()
            counter.opened += 1
            counter.active += 1
            return result

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            try:
                await super().__aexit__(exc_type, exc_value, traceback)
            finally:
                counter.active -= 1

    with override_session_factory(
        async_sessionmaker(engine, class_=CountedSession, expire_on_commit=False)
    ):
        yield counter


@pytest.mark.parametrize("state", ["missing", "random", "expired", "revoked"])
async def test_invalid_sessions_finish_as_json(
    client: httpx.AsyncClient, login_and_list: UUID, state: str
) -> None:
    if state == "missing":
        client.cookies.clear()
    elif state == "random":
        client.cookies.clear()
        client.cookies.set(COOKIE, "random-token")
    else:
        async with unit_of_work():
            session = await session_repo.by_token_hash(token_hash(client.cookies[COOKIE]))
            assert session is not None
            if state == "expired":
                session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                await session_repo.delete(session)
    async with asyncio.timeout(2):
        response = await client.get("/api/events", params={"shopping_list_id": str(login_and_list)})
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"code": "not_authenticated", "message": "Требуется вход"}


async def test_foreign_and_missing_lists_finish_as_same_json(
    client: httpx.AsyncClient, login_and_list: UUID, foreign_item: ItemRead
) -> None:
    responses = []
    for shopping_list_id in (foreign_item.shopping_list_id, uuid7()):
        async with asyncio.timeout(2):
            responses.append(
                await client.get("/api/events", params={"shopping_list_id": str(shopping_list_id)})
            )
    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].headers["content-type"] == "application/json"
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["code"] == "shopping_list_not_found"


async def test_missing_list_id_finishes_as_validation_json(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    async with asyncio.timeout(2):
        response = await client.get("/api/events")
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"][0]["loc"] == ["query", "shopping_list_id"]


@pytest.mark.real_commits
async def test_sse_gets_committed_event_and_releases_subscription(
    sse_client: SseClient,
    client: httpx.AsyncClient,
    login_and_list: UUID,
    session_counter: SessionCounter,
) -> None:
    def check_start() -> None:
        assert session_counter.active == 0
        # Observe the real hub registry, without replacing subscription behavior.
        assert len(event_hub._subscribers[login_and_list]) == 1

    before = session_counter.opened
    async with sse_client.connect(
        "/api/events", shopping_list_id=login_and_list, cookies=client.cookies, on_start=check_start
    ) as stream:
        await stream.started()
        assert stream.status == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-cache"
        assert stream.headers["x-accel-buffering"] == "no"
        assert session_counter.opened == before + 1
        assert session_counter.active == 0
        added = await client.post(
            "/api/items",
            headers={"X-Device-Id": "phone"},
            json={
                "shopping_list_id": str(login_and_list),
                "items": [{"name": "Лук", "quantity": 2}],
            },
        )
        assert added.status_code == 200
        frame = await stream.next_data()
        assert frame["type"] == "items_added"
        assert frame["payload"]["results"] == added.json()
        assert frame["payload"]["items"] == []
        assert frame["payload"]["results"][0]["item"]["name"] == "Лук"
        assert frame["payload"]["results"][0]["item"]["quantity"] == 2
        async with unit_of_work() as session:
            stored = await session.get(Event, UUID(frame["id"]))
            assert stored is not None
            assert frame == EventRead.model_validate(stored).model_dump(mode="json")
        assert session_counter.active == 0
        task = stream.task
    assert task.done()
    assert not task.cancelled()
    assert login_and_list not in event_hub._subscribers
    assert session_counter.active == 0


@pytest.mark.real_commits
async def test_other_lists_and_rolled_back_events_are_not_delivered(
    sse_client: SseClient,
    client: httpx.AsyncClient,
    login_and_list: UUID,
    session_counter: SessionCounter,
) -> None:
    async with sse_client.connect(
        "/api/events", shopping_list_id=login_and_list, cookies=client.cookies
    ) as stream:
        await stream.started()
        async with unit_of_work():
            other = await auth.create_user("boris", "test-password")
            with auth.acting_as(other):
                await service.add_items(
                    AddItems(
                        shopping_list_id=await service.get_default_shopping_list_id(),
                        items=[ItemCreate(name="Чай")],
                    ),
                    AppSource(device_id="other-phone"),
                )

        async def roll_back_mutation() -> None:
            async with unit_of_work():
                with auth.acting_as(await auth.resolve_session(client.cookies[COOKIE])):
                    await service.add_items(
                        AddItems(shopping_list_id=login_and_list, items=[ItemCreate(name="Откат")]),
                        AppSource(device_id="phone"),
                    )
                    raise RuntimeError("force rollback")

        with pytest.raises(RuntimeError, match="force rollback"):
            await roll_back_mutation()
        with pytest.raises(TimeoutError):
            await stream.next_data(timeout=0.1)
        assert session_counter.active == 0
        async with unit_of_work() as session:
            assert (
                await session.scalar(select(Event).where(Event.shopping_list_id == login_and_list))
                is None
            )
        added = await client.post(
            "/api/items",
            headers={"X-Device-Id": "phone"},
            json={"shopping_list_id": str(login_and_list), "items": [{"name": "Лук"}]},
        )
        assert added.status_code == 200
        assert (await stream.next_data())["payload"]["results"] == added.json()
    assert login_and_list not in event_hub._subscribers


def test_openapi_documents_typed_sse_and_cookie_security(app: FastAPI) -> None:
    schema = app.openapi()
    route = schema["paths"]["/api/events"]["get"]
    assert route["security"] == [{"SessionCookie": []}]
    stream_schema = route["responses"]["200"]["content"]["text/event-stream"]
    assert stream_schema["itemSchema"]["properties"]["data"] == {
        "type": "string",
        "contentMediaType": "application/json",
        "contentSchema": {"$ref": "#/components/schemas/ShoppingListEventRead"},
    }
    union = schema["components"]["schemas"]["ShoppingListEventRead"]
    assert union["discriminator"]["propertyName"] == "type"
    assert set(union["discriminator"]["mapping"]) == {event.value for event in EventType}
    assert len(union["oneOf"]) == 9
    for status in (401, 404, 409, 422, 500):
        content = route["responses"][str(status)]["content"]
        assert set(content) == {"application/json"}
        assert content["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


@pytest.mark.parametrize("event_type", list(EventType))
def test_all_event_variants_preserve_snapshot_json(event_type: EventType) -> None:
    from grocery.schemas.events import ShoppingListEventRead

    snapshot = EventRead(
        id=uuid7(),
        shopping_list_id=uuid7(),
        user_id=uuid7(),
        type=event_type,
        source=AppSource(device_id="phone"),
        payload=EventPayload(),
        created_at=datetime.now(UTC),
    )
    result = ShoppingListEventRead.model_validate(snapshot.model_dump())
    assert result.model_dump(mode="json") == snapshot.model_dump(mode="json")
