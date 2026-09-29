#!/usr/bin/env bash
# Форматирование и автоисправления ruff (ADR-0007).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run ruff format .
uv run ruff check --fix .
