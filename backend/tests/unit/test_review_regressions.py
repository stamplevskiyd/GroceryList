"""Security and contract regressions from the PAT/MCP review."""

import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from grocery.config import get_settings
from grocery.domain.enums import EventType
from grocery.main import create_app, lifespan
from grocery.mcp_server.middleware import domain_errors
from grocery.mcp_server.tools import build_tools
from grocery.schemas.events import EventCreate, ItemsPayload, ShoppingListEventRead
from grocery.schemas.items import ItemCreate, ItemUpdate
from grocery.schemas.sources import AppSource
from grocery.schemas.tags import TagCreate, TagUpdate
from tests.support import REPO_ROOT


async def test_internal_validation_error_is_safe(caplog: pytest.LogCaptureFixture) -> None:
    class InternalResult(BaseModel):
        count: int

    @domain_errors
    async def broken() -> None:
        InternalResult.model_validate({"count": "PRIVATE_RESULT_VALUE"})

    with pytest.raises(ToolError, match=r"^Внутренняя ошибка$") as caught:
        await broken()
    assert "PRIVATE_RESULT_VALUE" not in str(caught.value)
    assert "InternalResult" not in str(caught.value)
    assert "MCP handler failed" in caplog.text


@pytest.mark.parametrize("schema", [ItemCreate, ItemUpdate, TagUpdate])
def test_unicode_expansion_name_is_rejected(schema: type[BaseModel]) -> None:
    with pytest.raises(ValidationError, match="Нормализованное название"):
        schema.model_validate({"name": "İ" * 128})


@pytest.mark.parametrize("schema", [ItemCreate, ItemUpdate])
def test_unicode_expansion_unit_and_tags_are_rejected(schema: type[BaseModel]) -> None:
    with pytest.raises(ValidationError, match="Нормализованная единица"):
        schema.model_validate({"name": "Лук", "unit": "İ" * 33})
    with pytest.raises(ValidationError, match="Нормализованное название"):
        schema.model_validate({"name": "Лук", "tags": ["İ" * 128]})
    with pytest.raises(ValidationError):
        TagCreate(name="İ" * 128, shopping_list_id=uuid7())


def test_flat_mcp_patch_inherits_entire_rest_schema() -> None:
    tool = next(tool for tool in build_tools() if tool.name == "update_item")
    rest = ItemUpdate.model_json_schema()
    for field, schema in rest["properties"].items():
        assert tool.parameters["properties"][field] == schema
    assert tool.parameters["additionalProperties"] is False
    assert tool.parameters["required"] == ["id"]


@pytest.mark.parametrize("event_type", list(EventType))
def test_missing_payload_fields_are_rejected(event_type: EventType) -> None:
    with pytest.raises(ValidationError):
        ShoppingListEventRead.model_validate(
            {
                "id": uuid7(),
                "shopping_list_id": uuid7(),
                "user_id": uuid7(),
                "type": event_type,
                "source": {"kind": "app", "device_id": "phone"},
                "created_at": datetime.now(UTC),
                "payload": {},
            }
        )


def test_event_create_rejects_wrong_payload_type() -> None:
    with pytest.raises(ValidationError, match="Payload не соответствует"):
        EventCreate(
            shopping_list_id=uuid7(),
            user_id=uuid7(),
            type=EventType.TAGS_MERGED,
            source=AppSource(device_id="phone"),
            payload=ItemsPayload(items=[]),
        )


@pytest.mark.parametrize("method", ["commit", "rollback"])
def test_transaction_guard_rejects_calls_outside_uow(tmp_path: Path, method: str) -> None:
    script = REPO_ROOT / "scripts/check_transactions.py"
    (tmp_path / "service.py").write_text(f"async def bad(session):\n    await session.{method}()\n")
    result = subprocess.run(  # noqa: S603 — fixed checker and pytest temp path
        [sys.executable, str(script), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert f"service.py:2: {method}()" in result.stdout
    (tmp_path / "service.py").write_text("# session.commit() is only a comment\n")
    (tmp_path / "db").mkdir()
    (tmp_path / "db/session.py").write_text(
        f"async def allowed(session):\n    await session.{method}()\n"
    )
    assert (
        subprocess.run(  # noqa: S603 — fixed checker and pytest temp path
            [sys.executable, str(script), str(tmp_path)], capture_output=True, check=False
        ).returncode
        == 0
    )


@pytest.mark.parametrize("level", ["DEBUG", "WARNING", "ERROR"])
async def test_log_level_applies_at_startup(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    from grocery import main

    monkeypatch.setenv("APP_LOG_LEVEL", level)
    get_settings.cache_clear()
    monkeypatch.setattr(main, "configure_engine", lambda url: None)
    monkeypatch.setattr(main, "dispose_engine", AsyncMock())
    from grocery.services import auth

    monkeypatch.setattr(auth, "initialize_passwords", AsyncMock())
    root = logging.getLogger()
    previous = root.level
    try:
        app = create_app()
        assert app.state.mcp.settings.log_level == level
        async with lifespan(app):
            assert logging.getLogger("grocery.services").getEffectiveLevel() == getattr(
                logging, level
            )
            assert logging.getLogger("mcp.server").getEffectiveLevel() == getattr(logging, level)
    finally:
        root.setLevel(previous)


def test_invalid_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOG_LEVEL", "VERBOSE")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
