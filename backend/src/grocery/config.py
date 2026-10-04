"""Настройки приложения — единственное место чтения окружения (ADR-0006).

Имена переменных: <ГРУППА>_<ПОЛЕ>, например DB_URL → settings.db.url.
"""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    public_url: HttpUrl

    @field_validator("public_url")
    @classmethod
    def origin_only(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.path not in (None, "/")
            or value.query
            or value.fragment
            or value.username
            or value.password
        ):
            raise ValueError(
                "APP_PUBLIC_URL должен быть origin без path, query, fragment и credentials"
            )
        return value

    @property
    def origin(self) -> str:
        return str(self.public_url).rstrip("/")

    @property
    def mcp_url(self) -> str:
        return self.origin + "/mcp"

    version: str = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class DbSettings(BaseModel):
    url: PostgresDsn


class AuthSettings(BaseModel):
    oauth_access_ttl_seconds: int = Field(default=3600, gt=0)
    oauth_refresh_ttl_seconds: int = Field(default=2592000, gt=0)
    oauth_code_ttl_seconds: int = Field(default=300, gt=0)
    oauth_request_ttl_seconds: int = Field(default=600, gt=0)
    oauth_refresh_grace_seconds: int = Field(default=60, gt=0)
    cimd_timeout_seconds: float = Field(default=5, gt=0, le=8)
    cimd_max_bytes: int = Field(default=65536, gt=0)
    session_ttl_seconds: int = Field(default=2592000, gt=0)
    login_username_limit: int = Field(default=5, gt=0)
    login_ip_limit: int = Field(default=30, gt=0)
    login_window_seconds: int = Field(default=300, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Из backend/ читается .env в корне репозитория; в контейнере переменные приходят
        # из окружения, файла нет.
        env_file=("../.env", ".env"),
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="ignore",
    )

    app: AppSettings
    db: DbSettings
    auth: AuthSettings = Field(default_factory=AuthSettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()
