"""Настройки: переменные <ГРУППА>_<ПОЛЕ>, ошибки конфигурации, .env.example (ADR-0006)."""

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from grocery.config import AuthSettings, Settings, get_settings
from tests.support import REPO_ROOT


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Settings читает .env из рабочей директории — изолируемся от локального файла разработчика.
    monkeypatch.chdir(tmp_path)


def test_reads_groups_with_single_underscore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", "https://grocery.example")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:secret@db:5432/grocery")

    settings = Settings()

    assert settings.app.public_url.host == "grocery.example"
    assert settings.app.log_level == "DEBUG"
    assert settings.app.version == "dev"
    assert settings.db.url.hosts()[0]["host"] == "db"


def test_missing_group_names_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "db" in {error["loc"][0] for error in exc_info.value.errors()}


def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", "not a url")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert ("app", "public_url") in {error["loc"] for error in exc_info.value.errors()}


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_auth_defaults_support_existing_environment() -> None:
    assert Settings().auth.model_dump() == {
        "session_ttl_seconds": 2592000,
        "login_username_limit": 5,
        "login_ip_limit": 30,
        "login_window_seconds": 300,
    }


def test_auth_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "60")
    monkeypatch.setenv("AUTH_LOGIN_USERNAME_LIMIT", "2")
    monkeypatch.setenv("AUTH_LOGIN_IP_LIMIT", "10")
    monkeypatch.setenv("AUTH_LOGIN_WINDOW_SECONDS", "120")
    assert Settings().auth == AuthSettings(
        session_ttl_seconds=60,
        login_username_limit=2,
        login_ip_limit=10,
        login_window_seconds=120,
    )


@pytest.mark.parametrize("field", list(AuthSettings.model_fields))
@pytest.mark.parametrize("value", [0, -1])
def test_auth_settings_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        AuthSettings.model_validate({field: value})


def _env_names() -> list[str]:
    names = []
    for group_name, group_field in Settings.model_fields.items():
        group_model = group_field.annotation
        assert isinstance(group_model, type)
        assert issubclass(group_model, BaseModel)
        names += [f"{group_name}_{field}".upper() for field in group_model.model_fields]
    return names


def test_group_names_have_no_underscore() -> None:
    # env_nested_max_split=1 делит имя по первому «_» — в имени группы его быть не должно.
    assert all("_" not in group for group in Settings.model_fields)


def test_env_example_lists_every_setting() -> None:
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    declared = {line.split("=", 1)[0] for line in lines if "=" in line and not line.startswith("#")}

    assert set(_env_names()) <= declared


@pytest.mark.parametrize(
    "url",
    [
        "https://grocery.example/path",
        "https://grocery.example/?q=x",
        "https://grocery.example/#x",
        "https://user:secret@grocery.example",
    ],
)
def test_public_url_must_be_origin(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", url)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "url", ["https://grocery.example", "https://grocery.example/", "http://127.0.0.1:8765/"]
)
def test_mcp_url_canonical(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", url)
    assert Settings().app.mcp_url == url.rstrip("/") + "/mcp"
