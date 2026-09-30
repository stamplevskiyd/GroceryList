#!/usr/bin/env bash
# Проверка типов: mypy strict (ADR-0002).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run mypy
npm --prefix ../frontend run typecheck
