"""Общие константы тестов."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Тот же тег, что у сервиса postgres в docker-compose.yml (проверяет tests/unit/test_compose.py).
POSTGRES_IMAGE = "postgres:18-alpine"
