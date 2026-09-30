"""Item REST contract exercised through real HTTP and PostgreSQL."""

from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from grocery.db.models import Event
from grocery.db.session import unit_of_work
from grocery.schemas.items import AddItems, ItemCreate, ItemRead
from grocery.schemas.sources import McpSource
from grocery.services import auth
from grocery.services import shopping_list_service as service

HEADERS = {"X-Device-Id": "phone"}
ROUTES = [
    ("GET", "/api/items"),
    ("POST", "/api/items"),
    ("POST", "/api/items/quick-add"),
    ("PATCH", "/api/items/{id}"),
    ("DELETE", "/api/items/{id}"),
    ("POST", "/api/items/bought"),
    ("POST", "/api/items/clear-bought"),
]


async def test_item_lifecycle(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    response = await client.post(
        "/api/items",
        headers={"X-Device-Id": "  tablet  "},
        json={
            "shopping_list_id": str(login_and_list),
            "items": [
                {
                    "name": "Молоко",
                    "quantity": 1.5,
                    "unit": "л",
                    "tags": ["Завтрак"],
                    "note": "безлактозное",
                },
                {"name": "Чай", "note": "зелёный"},
            ],
        },
    )
    assert response.status_code == 200
    milk, tea = response.json()
    assert milk["status"] == tea["status"] == "created"
    item_id = milk["item"]["id"]
    assert milk["item"]["quantity"] == 1500
    assert isinstance(milk["item"]["quantity"], (int, float))
    assert milk["item"]["sources"] == [{"kind": "app"}]
    response = await client.post(
        "/api/items/quick-add",
        headers=HEADERS,
        json={"shopping_list_id": str(login_and_list), "text": "молоко 500 мл"},
    )
    assert response.status_code == 200
    assert response.json()["parsed"]["quantity"] == 500
    assert response.json()["result"]["status"] == "merged"
    merged = response.json()["result"]["item"]
    assert (merged["id"], merged["name"], merged["quantity"]) == (item_id, "Молоко", 2000)
    assert merged["note"] == "безлактозное"
    response = await client.patch(
        f"/api/items/{item_id}",
        headers=HEADERS,
        json={"quantity": None, "note": None, "tags": []},
    )
    assert response.status_code == 200
    assert response.json()["quantity"] is None
    assert response.json()["note"] is None
    assert response.json()["tags"] == []
    assert response.json()["unit"] == "мл"
    bought_body = {"shopping_list_id": str(login_and_list), "ids": [item_id], "bought": True}
    response = await client.post("/api/items/bought", headers=HEADERS, json=bought_body)
    assert response.status_code == 200
    assert response.json()[0]["is_bought"] is True
    assert response.json()[0]["bought_at"] is not None
    params = {"shopping_list_id": str(login_and_list)}
    current = await client.get("/api/items", params=params)
    assert [item["id"] for item in current.json()] == [tea["item"]["id"]]
    assert (
        len((await client.get("/api/items", params={**params, "include_bought": True})).json()) == 2
    )
    response = await client.post(
        "/api/items/bought", headers=HEADERS, json={**bought_body, "bought": False}
    )
    assert response.status_code == 200
    assert response.json()[0]["is_bought"] is False
    assert response.json()[0]["bought_at"] is None
    assert (
        await client.post("/api/items/bought", headers=HEADERS, json=bought_body)
    ).status_code == 200
    response = await client.post("/api/items/clear-bought", headers=HEADERS, json=params)
    assert response.status_code == 200
    assert response.json() == {"count": 1}
    response = await client.delete(f"/api/items/{tea['item']['id']}", headers=HEADERS)
    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get("/api/items", params=params)).json() == []
    async with unit_of_work() as db:
        events = list(await db.scalars(select(Event).order_by(Event.id)))
        assert len(events) == 8
        assert events[0].source.model_dump() == {"kind": "app", "device_id": "tablet"}
        assert all(
            event.source.model_dump() == {"kind": "app", "device_id": "phone"}
            for event in events[1:]
        )


async def test_item_sources_hide_device_and_client_identifiers(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    # The future MCP adapter shares this service; seed its attribution without mocking it.
    async with unit_of_work():
        with auth.acting_as(await auth.resolve_session(client.cookies["__Host-gl_session"])):
            await service.add_items(
                AddItems(shopping_list_id=login_and_list, items=[ItemCreate(name="Чай")]),
                McpSource(client_id="private-client-id", client_name="Claude"),
            )
    response = await client.post(
        "/api/items",
        headers={"X-Device-Id": "private-device-id"},
        json={"shopping_list_id": str(login_and_list), "items": [{"name": "Чай"}]},
    )
    assert response.status_code == 200
    assert response.json()[0]["item"]["sources"] == [
        {"kind": "mcp", "client_name": "Claude"},
        {"kind": "app"},
    ]
    response = await client.get("/api/items", params={"shopping_list_id": str(login_and_list)})
    assert response.status_code == 200
    assert response.json()[0]["sources"] == [
        {"kind": "mcp", "client_name": "Claude"},
        {"kind": "app"},
    ]
    assert "private-client-id" not in response.text
    assert "private-device-id" not in response.text


async def test_invalid_batch_is_atomic(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    response = await client.post(
        "/api/items",
        headers=HEADERS,
        json={
            "shopping_list_id": str(login_and_list),
            "items": [{"name": "Лук"}, {"name": "Молоко", "quantity": -1}],
        },
    )
    assert response.status_code == 422
    assert response.json()["details"][0]["loc"] == ["body", "items", 1, "quantity"]
    current = await client.get("/api/items", params={"shopping_list_id": str(login_and_list)})
    assert current.json() == []
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Event)) == 0


async def test_invalid_bought_batch_is_atomic(
    client: httpx.AsyncClient, login_and_list: UUID, foreign_item: ItemRead
) -> None:
    added = await client.post(
        "/api/items",
        headers=HEADERS,
        json={"shopping_list_id": str(login_and_list), "items": [{"name": "Лук"}]},
    )
    item_id = added.json()[0]["item"]["id"]
    for invalid_id in (str(uuid7()), str(foreign_item.id)):
        response = await client.post(
            "/api/items/bought",
            headers=HEADERS,
            json={
                "shopping_list_id": str(login_and_list),
                "ids": [item_id, invalid_id],
                "bought": True,
            },
        )
        assert response.status_code == 404
    current = await client.get("/api/items", params={"shopping_list_id": str(login_and_list)})
    assert current.json()[0]["is_bought"] is False
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Event)) == 2


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_authentication_precedes_header_and_schema_validation(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path.format(id="bad-uuid"), json={"unknown": True})
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


@pytest.mark.parametrize(("method", "path"), ROUTES[1:])
@pytest.mark.parametrize("device_id", [None, " ", "x" * 129])
async def test_mutations_require_valid_device_header(
    client: httpx.AsyncClient, login_and_list: UUID, method: str, path: str, device_id: str | None
) -> None:
    headers = {} if device_id is None else {"X-Device-Id": device_id}
    response = await client.request(method, path.format(id=uuid7()), headers=headers, json={})
    assert response.status_code == 422
    assert ["header", "X-Device-Id"] in [detail["loc"] for detail in response.json()["details"]]


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("existing", [True, False])
async def test_foreign_and_missing_objects_are_404(
    client: httpx.AsyncClient,
    login_and_list: UUID,
    foreign_item: ItemRead,
    method: str,
    path: str,
    existing: bool,
) -> None:
    shopping_list_id = str(foreign_item.shopping_list_id if existing else uuid7())
    response = await client.request(
        method,
        path.format(id=foreign_item.id if existing else uuid7()),
        headers=HEADERS,
        params={"shopping_list_id": shopping_list_id},
        json={
            "POST /api/items": {"shopping_list_id": shopping_list_id, "items": [{"name": "Лук"}]},
            "POST /api/items/quick-add": {"shopping_list_id": shopping_list_id, "text": "лук"},
            "POST /api/items/bought": {
                "shopping_list_id": shopping_list_id,
                "ids": [str(foreign_item.id)],
                "bought": True,
            },
            "POST /api/items/clear-bought": {"shopping_list_id": shopping_list_id},
            "PATCH /api/items/{id}": {"note": "new"},
        }.get(f"{method} {path}"),
    )
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_invalid_identifiers_are_422(
    client: httpx.AsyncClient, login_and_list: UUID, method: str, path: str
) -> None:
    response = await client.request(
        method,
        path.format(id="bad-uuid"),
        headers=HEADERS,
        params={"shopping_list_id": "bad-uuid"},
        json={
            "shopping_list_id": "bad-uuid",
            "items": [{"name": "Лук"}],
            "ids": ["bad-uuid"],
            "bought": True,
            "text": "лук",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/items", {"items": [{"name": "Лук"}]}),
        ("/api/items/quick-add", {"text": "лук"}),
        ("/api/items/bought", {"ids": [str(uuid7())], "bought": True}),
        ("/api/items/clear-bought", {}),
    ],
)
async def test_list_id_is_required_in_body(
    client: httpx.AsyncClient, login_and_list: UUID, path: str, body: dict[str, object]
) -> None:
    response = await client.post(path, headers=HEADERS, json=body)
    assert response.status_code == 422
    assert ["body", "shopping_list_id"] in [detail["loc"] for detail in response.json()["details"]]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/items", {"items": []}),
        ("/api/items/bought", {"ids": [], "bought": True}),
        ("/api/items", {"items": [{"name": "Лук", "device_id": "forged"}]}),
        (
            "/api/items",
            {"items": [{"name": "Лук"}], "source": {"kind": "app", "device_id": "forged"}},
        ),
        ("/api/items/quick-add", {"text": "лук", "source": {"kind": "app"}}),
        ("/api/items/bought", {"ids": [str(uuid7())], "bought": True, "unknown": 1}),
        ("/api/items/clear-bought", {"unknown": 1}),
    ],
)
async def test_empty_batches_and_unknown_fields_are_422(
    client: httpx.AsyncClient, login_and_list: UUID, path: str, body: dict[str, object]
) -> None:
    response = await client.post(
        path, headers=HEADERS, json={"shopping_list_id": str(login_and_list), **body}
    )
    assert response.status_code == 422


async def test_patch_rejects_unknown_fields(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    response = await client.patch(
        f"/api/items/{uuid7()}", headers=HEADERS, json={"name_normalized": "forged"}
    )
    assert response.status_code == 422


async def test_read_requires_list_id(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    assert (await client.get("/api/items")).status_code == 422


@pytest.mark.parametrize(
    ("method", "path"), [route for route in ROUTES if route[0] in {"POST", "PATCH"}]
)
async def test_malformed_json_is_parsed_before_authentication(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(
        method,
        path.format(id=uuid7()),
        headers={"Content-Type": "application/json"},
        content=b'{"private":',
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"][0]["loc"][0] == "body"
    assert "private" not in response.text


def test_items_openapi_contract(app: FastAPI) -> None:
    schema = app.openapi()
    for method, path in ROUTES:
        route = schema["paths"][path][method.lower()]
        assert route["security"] == [{"SessionCookie": []}]
        for status in (401, 404, 409, 422, 500):
            assert route["responses"][str(status)]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
        if method != "GET":
            header = next(
                parameter for parameter in route["parameters"] if parameter["name"] == "X-Device-Id"
            )
            assert header["required"] is True
    assert "content" not in schema["paths"]["/api/items/{id}"]["delete"]["responses"]["204"]
    assert not any(name.endswith(("-Input", "-Output")) for name in schema["components"]["schemas"])
