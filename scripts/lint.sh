#!/usr/bin/env bash
# Линтеры: формат, правила ruff, границы слоёв, shell-скрипты (ADR-0007).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run ruff format --check .
uv run ruff check .
uv run lint-imports
uv run python ../scripts/check_transactions.py
uv run ruff check ../scripts/check_transactions.py
uv run ruff format --check ../scripts/check_transactions.py
cd ..
uv run --project backend shellcheck scripts/*.sh
uv run --project backend actionlint .github/workflows/*.yml
