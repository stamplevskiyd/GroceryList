"""Published HTTP contract and offline CLI export (ADR-0009)."""

import getpass
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from grocery import __main__ as cli
from grocery import main as application
from grocery.config import get_settings
from grocery.db import session
from grocery.domain.enums import EventType
from grocery.main import create_app
from grocery.services import auth

# OpenAPI is a heterogeneous JSON document returned by FastAPI as dict[str, Any].
JsonSchema = dict[str, Any]

OPERATIONS = [
    ("/api/health", "get", 200, "HealthRead", False),
    ("/api/auth/login", "post", 200, "MeRead", False),
    ("/api/auth/logout", "post", 204, None, True),
    ("/api/me", "get", 200, "MeRead", True),
    ("/api/items", "get", 200, "ItemRead", True),
    ("/api/items", "post", 200, "AddItemResult", True),
    ("/api/items/quick-add", "post", 200, "QuickAddResult", True),
    ("/api/items/{id}", "patch", 200, "ItemRead", True),
    ("/api/items/{id}", "delete", 204, None, True),
    ("/api/items/bought", "post", 200, "ItemRead", True),
    ("/api/items/clear-bought", "post", 200, "CountRead", True),
    ("/api/tags", "get", 200, "TagUsageRead", True),
    ("/api/tags", "post", 201, "TagRead", True),
    ("/api/tags/{id}", "patch", 200, "TagRead", True),
    ("/api/tags/{id}", "delete", 204, None, True),
    ("/api/tags/{id}/bulk", "post", 200, "CountRead", True),
    ("/api/events", "get", 200, "ShoppingListEventRead", True),
    ("/api/tokens", "get", 200, "TokenRead", True),
    ("/api/tokens", "post", 200, "TokenIssued", True),
    ("/api/tokens/{id}", "delete", 204, None, True),
]


@pytest.fixture
def schema() -> JsonSchema:
    return create_app().openapi()


@pytest.mark.parametrize(("path", "method", "status", "model", "protected"), OPERATIONS)
def test_openapi_http_contract(
    schema: JsonSchema, path: str, method: str, status: int, model: str | None, protected: bool
) -> None:
    operation = schema["paths"][path][method]
    assert operation.get("security", []) == ([{"SessionCookie": []}] if protected else [])
    success = operation["responses"][str(status)]
    assert success["description"]
    if model is None:
        assert "content" not in success
    else:
        content = success["content"]
        media_type = "text/event-stream" if path == "/api/events" else "application/json"
        if path == "/api/events":
            data = content[media_type]["itemSchema"]["properties"]["data"]
            assert data == {
                "type": "string",
                "contentMediaType": "application/json",
                "contentSchema": {"$ref": f"#/components/schemas/{model}"},
            }
        else:
            response_schema = content[media_type]["schema"]
            reference = {"$ref": f"#/components/schemas/{model}"}
            if response_schema.get("type") == "array":
                assert response_schema["items"] == reference
            else:
                assert response_schema == reference
    if method in {"post", "patch", "delete"}:
        headers = [p for p in operation["parameters"] if p["in"] == "header"]
        assert any(p["name"] == "X-Device-Id" and p["required"] for p in headers)
    errors = (401, 404, 409, 422, 500) if protected else (401, 422, 429, 500)
    if path == "/api/health":
        return
    for error_status in errors:
        response = operation["responses"][str(error_status)]
        assert response["description"]
        assert set(response["content"]) == {"application/json"}
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


def test_openapi_read_quantity_schema_is_numeric(schema: JsonSchema) -> None:
    quantity = schema["components"]["schemas"]["ItemRead"]["properties"]["quantity"]
    assert {part["type"] for part in quantity["anyOf"]} == {"number", "null"}


def test_openapi_no_direction_suffixes_or_default_validation(schema: JsonSchema) -> None:
    schemas = schema["components"]["schemas"]
    assert not any(name.endswith(("-Input", "-Output")) for name in schemas)
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert schema["components"]["securitySchemes"]["SessionCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "__Host-gl_session",
    }
    assert not {"token", "raw_token", "session_token", "password", "password_hash"} & set(
        schemas["MeRead"]["properties"]
    )


def test_openapi_named_sse_union(schema: JsonSchema) -> None:
    union = schema["components"]["schemas"]["ShoppingListEventRead"]
    assert union["discriminator"]["propertyName"] == "type"
    assert set(union["discriminator"]["mapping"]) == {
        "items_added",
        "item_updated",
        "items_bought",
        "items_unbought",
        "items_deleted",
        "bought_cleared",
        "tag_created",
        "tag_renamed",
        "tags_merged",
        "tag_deleted",
    }
    assert set(union["discriminator"]["mapping"]) == {event.value for event in EventType}
    assert len(union["oneOf"]) == len(union["discriminator"]["mapping"])


@pytest.mark.parametrize(
    ("path", "method", "model"),
    [
        ("/api/auth/login", "post", "LoginCreate"),
        ("/api/items", "post", "AddItems"),
        ("/api/items/quick-add", "post", "QuickAdd"),
        ("/api/items/{id}", "patch", "ItemUpdate"),
        ("/api/items/bought", "post", "SetBought"),
        ("/api/items/clear-bought", "post", "ClearBought"),
        ("/api/tags/{id}", "patch", "TagUpdate"),
        ("/api/tags", "post", "TagCreate"),
        ("/api/tags/{id}/bulk", "post", "TagBulk"),
    ],
)
def test_openapi_request_models(schema: JsonSchema, path: str, method: str, model: str) -> None:
    body = schema["paths"][path][method]["requestBody"]
    assert body["required"]
    assert body["content"]["application/json"]["schema"] == {
        "$ref": f"#/components/schemas/{model}"
    }
    if model in {"TagCreate", "TagUpdate"}:
        tag_schema = schema["components"]["schemas"][model]
        expected_fields = {"name", "shopping_list_id"} if model == "TagCreate" else {"name"}
        assert set(tag_schema["properties"]) == expected_fields
        assert tag_schema["additionalProperties"] is False


@pytest.mark.parametrize("path", ["/api/items", "/api/tags", "/api/events"])
def test_openapi_read_list_query_is_required(schema: JsonSchema, path: str) -> None:
    parameters = schema["paths"][path]["get"]["parameters"]
    assert any(
        p["name"] == "shopping_list_id" and p["in"] == "query" and p["required"] for p in parameters
    )


@pytest.fixture
def export_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", "http://localhost")
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
    monkeypatch.setenv("APP_VERSION", "host-dependent-version")
    get_settings.cache_clear()


def _export(*args: str) -> subprocess.CompletedProcess[str]:
    # Test runs the installed interpreter and module, without shell evaluation.
    return subprocess.run(  # noqa: S603 — fixed executable/module; arguments are test-owned paths
        [sys.executable, "-m", "grocery", "export-openapi", *args],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.usefixtures("export_environment")
def test_openapi_export_stdout_is_deterministic_json() -> None:
    first = _export()
    second = _export()
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    exported = json.loads(first.stdout)
    assert exported["info"]["version"] == importlib.metadata.version("grocery")
    assert "servers" not in exported
    assert first.stdout == json.dumps(exported, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.mark.usefixtures("export_environment")
def test_openapi_export_output_and_invalid_path(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"
    result = _export("--output", str(output))
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    assert output.read_text() == _export().stdout
    invalid = _export("--output", str(tmp_path / "missing" / "openapi.json"))
    assert invalid.returncode != 0
    assert invalid.stderr
    assert invalid.stdout == ""


@pytest.mark.usefixtures("export_environment")
@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        "postgresql+asyncpg://export:unused@db.invalid:5432/foreign",
    ],
)
def test_openapi_export_never_prompts_or_initializes_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], database_url: str
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("offline export touched password prompt, engine, or lifespan")

    monkeypatch.setenv("DB_URL", database_url)
    get_settings.cache_clear()
    monkeypatch.setattr(getpass, "getpass", forbidden)
    monkeypatch.setattr(cli, "configure_engine", forbidden)
    monkeypatch.setattr(application, "configure_engine", forbidden)
    monkeypatch.setattr(session, "configure_engine", forbidden)
    monkeypatch.setattr(application, "lifespan", forbidden)
    monkeypatch.setattr(auth, "initialize_passwords", forbidden)
    assert cli.main(["export-openapi"]) == 0
    assert json.loads(capsys.readouterr().out)["info"]["version"] == importlib.metadata.version(
        "grocery"
    )
