"""Общие константы и помощники тестов."""

from pathlib import Path

from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Тот же тег, что у сервиса postgres в docker-compose.yml (проверяет tests/unit/test_compose.py).
POSTGRES_IMAGE = "postgres:18-alpine"


def alembic_config(database_url: str) -> Config:
    """Конфиг Alembic, нацеленный на указанную базу."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # configparser трактует «%» как интерполяцию.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config
