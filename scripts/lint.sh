#!/usr/bin/env bash
# Линтеры: формат, правила ruff, границы слоёв, shell-скрипты (ADR-0007).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run ruff format --check .
uv run ruff check .
uv run lint-imports
uv run shellcheck ../scripts/*.sh
