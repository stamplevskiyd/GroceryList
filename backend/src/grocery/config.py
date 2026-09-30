"""Настройки приложения — единственное место чтения окружения (ADR-0006).

Имена переменных: <ГРУППА>_<ПОЛЕ>, например DB_URL → settings.db.url.
"""

from functools import lru_cache

from pydantic import BaseModel, Field, HttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    public_url: HttpUrl
    version: str = "dev"
    log_level: str = "INFO"


class DbSettings(BaseModel):
    url: PostgresDsn


class AuthSettings(BaseModel):
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
