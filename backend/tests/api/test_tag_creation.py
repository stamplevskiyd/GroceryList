"""Standalone tags: list ownership, normalization, committed SSE and duplicate races."""

import asyncio
from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from grocery.db.models import Event, Tag
from grocery.db.session import unit_of_work
from grocery.domain.enums import EventType
from grocery.schemas.events import EventRead
from grocery.schemas.items import ItemRead
from tests.support_sse import SseClient

HEADERS = {"X-Device-Id": "phone"}


@pytest.mark.real_commits
async def test_create_unused_tag_persists_emits_sse_and_can_be_assigned(
    app: FastAPI, client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    async with SseClient(app).connect(
        "/api/events", shopping_list_id=login_and_list, cookies=client.cookies
    ) as stream:
        await stream.started()
        response = await client.post(
            "/api/tags",
            headers=HEADERS,
            json={"shopping_list_id": str(login_and_list), "name": "  На   неделю  "},
        )
        assert response.status_code == 201
        tag = response.json()
        assert tag["name"] == "На неделю"
        frame = await stream.next_data()
        assert frame["type"] == "tag_created"
        assert frame["payload"] == {"tag": tag}
        async with unit_of_work() as session:
            stored = await session.get(Event, UUID(frame["id"]))
            assert stored is not None
            assert EventRead.model_validate(stored).model_dump(mode="json") == frame
    params = {"shopping_list_id": str(login_and_list)}
    assert (await client.get("/api/tags", params=params)).json() == [{**tag, "open_count": 0}]
    assert (await client.get("/api/items", params=params)).json() == []
    added = await client.post(
        "/api/items",
        headers=HEADERS,
        json={**params, "items": [{"name": "Хлеб", "tags": ["на неделю"]}]},
    )
    assert added.status_code == 200
    assert added.json()[0]["item"]["tags"] == [tag]
    assert (await client.get("/api/tags", params=params)).json() == [{**tag, "open_count": 1}]


@pytest.mark.real_commits
async def test_concurrent_normalized_duplicate_creates_one_tag_and_event(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/tags",
                headers=HEADERS,
                json={
                    "shopping_list_id": str(login_and_list),
                    "name": name,
                },
            )
            for name in ("  Зелёные  овощи ", "зеленые овощи")
        ]
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["message"] == "Тег с таким названием уже существует"
    async with unit_of_work() as session:
        assert await session.scalar(select(func.count()).select_from(Tag)) == 1
        assert (
            await session.scalar(
                select(func.count()).select_from(Event).where(Event.type == EventType.TAG_CREATED)
            )
            == 1
        )


async def test_create_requires_login_before_validation(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/tags", json={"name": ""})
    assert response.status_code == 401


async def test_create_requires_device_header(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    response = await client.post(
        "/api/tags",
        json={"shopping_list_id": str(login_and_list), "name": "Овощи"},
    )
    assert response.status_code == 422
    assert ["header", "X-Device-Id"] in [detail["loc"] for detail in response.json()["details"]]


@pytest.mark.parametrize("existing", [True, False])
async def test_create_cannot_access_foreign_or_missing_list(
    client: httpx.AsyncClient, login_and_list: UUID, foreign_item: ItemRead, existing: bool
) -> None:
    list_id = foreign_item.shopping_list_id if existing else uuid7()
    response = await client.post(
        "/api/tags",
        headers=HEADERS,
        json={
            "shopping_list_id": str(list_id),
            "name": "Овощи",
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": " "},
        {"name": "x" * 256},
        {"name": "Овощи", "name_normalized": "fake"},
        {"name": "Овощи", "source": {"kind": "app"}},
        {"name": "Овощи", "shopping_list_id": "bad"},
    ],
)
async def test_create_rejects_invalid_and_extra_fields(
    client: httpx.AsyncClient, login_and_list: UUID, body: dict[str, object]
) -> None:
    response = await client.post(
        "/api/tags",
        headers=HEADERS,
        json={
            "shopping_list_id": str(login_and_list),
            **body,
        },
    )
    assert response.status_code == 422
