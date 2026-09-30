"""Tag adapters delegate rename, merge and bulk operations to the service."""

from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI

from grocery.schemas.items import ItemRead

HEADERS = {"X-Device-Id": "phone"}
ROUTES = [
    ("GET", "/api/tags"),
    ("PATCH", "/api/tags/{id}"),
    ("DELETE", "/api/tags/{id}"),
    ("POST", "/api/tags/{id}/bulk"),
]


async def test_tag_rename_merge_bulk_and_delete(
    client: httpx.AsyncClient, login_and_list: UUID
) -> None:
    response = await client.post(
        "/api/items",
        headers=HEADERS,
        json={
            "shopping_list_id": str(login_and_list),
            "items": [
                {"name": "Лук", "tags": ["Для супа", "Овощи"]},
                {"name": "Морковь", "tags": ["Овощи"]},
                {"name": "Чай", "tags": ["Завтрак"]},
            ],
        },
    )
    assert response.status_code == 200
    params = {"shopping_list_id": str(login_and_list)}
    response = await client.get("/api/tags", params=params)
    assert response.status_code == 200
    tags = {tag["name"]: tag for tag in response.json()}
    assert tags["Овощи"]["open_count"] == 2
    response = await client.patch(
        f"/api/tags/{tags['Для супа']['id']}", headers=HEADERS, json={"name": "овощи"}
    )
    assert response.status_code == 200
    assert response.json() == {"id": tags["Овощи"]["id"], "name": "Овощи"}
    response = await client.patch(
        f"/api/tags/{tags['Овощи']['id']}", headers=HEADERS, json={"name": "  Для  борща "}
    )
    assert response.status_code == 200
    assert response.json() == {"id": tags["Овощи"]["id"], "name": "Для борща"}
    response = await client.post(
        f"/api/tags/{tags['Овощи']['id']}/bulk", headers=HEADERS, json={"action": "mark_bought"}
    )
    assert response.status_code == 200
    assert response.json() == {"count": 2}
    current = await client.get("/api/items", params={**params, "include_bought": True})
    assert all(item["is_bought"] for item in current.json() if item["name"] != "Чай")
    current_tags = {
        tag["name"]: tag for tag in (await client.get("/api/tags", params=params)).json()
    }
    assert current_tags["Для борща"]["open_count"] == 0
    response = await client.post(
        f"/api/tags/{tags['Овощи']['id']}/bulk", headers=HEADERS, json={"action": "delete_items"}
    )
    assert response.status_code == 200
    assert response.json() == {"count": 2}
    response = await client.delete(f"/api/tags/{tags['Завтрак']['id']}", headers=HEADERS)
    assert response.status_code == 204
    assert response.content == b""
    current = await client.get("/api/items", params=params)
    assert len(current.json()) == 1
    assert current.json()[0]["name"] == "Чай"
    assert current.json()[0]["tags"] == []
    assert (await client.get("/api/tags", params=params)).json() == [
        {"id": tags["Овощи"]["id"], "name": "Для борща", "open_count": 0}
    ]


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
    response = await client.request(
        method,
        path.format(id=foreign_item.tags[0].id if existing else uuid7()),
        headers=HEADERS,
        params={"shopping_list_id": str(foreign_item.shopping_list_id if existing else uuid7())},
        json={"name": "Новое"} if method == "PATCH" else {"action": "mark_bought"},
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
        json={"name": "Новое"} if method == "PATCH" else {"action": "mark_bought"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": " "},
        {"name": "Новое", "name_normalized": "forged"},
        {"name": "Новое", "source": {"kind": "app", "device_id": "forged"}},
    ],
)
async def test_tag_update_rejects_invalid_and_forged_fields(
    client: httpx.AsyncClient, login_and_list: UUID, body: dict[str, object]
) -> None:
    response = await client.patch(f"/api/tags/{uuid7()}", headers=HEADERS, json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body", [{}, {"action": "unknown"}, {"action": "mark_bought", "unknown": 1}]
)
async def test_bulk_rejects_invalid_body(
    client: httpx.AsyncClient, login_and_list: UUID, body: dict[str, object]
) -> None:
    response = await client.post(f"/api/tags/{uuid7()}/bulk", headers=HEADERS, json=body)
    assert response.status_code == 422


async def test_read_requires_list_id(client: httpx.AsyncClient, login_and_list: UUID) -> None:
    assert (await client.get("/api/tags")).status_code == 422


@pytest.mark.parametrize(
    ("method", "path"), [("PATCH", "/api/tags/{id}"), ("POST", "/api/tags/{id}/bulk")]
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


def test_tags_openapi_contract(app: FastAPI) -> None:
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
    assert "content" not in schema["paths"]["/api/tags/{id}"]["delete"]["responses"]["204"]
    update = schema["components"]["schemas"]["TagUpdate"]
    assert set(update["properties"]) == {"name"}
    assert update["additionalProperties"] is False
    assert schema["paths"]["/api/tags/{id}"]["patch"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/TagRead"}
