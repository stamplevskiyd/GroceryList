#!/usr/bin/env bash
# Тесты (ADR-0011). `scripts/test.sh unit` — только быстрые тесты без Docker;
# остальные аргументы передаются pytest: `scripts/test.sh -k merge`.
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [[ "${1:-}" == "unit" ]]; then
  shift
  exec uv run pytest tests/unit "$@"
fi
exec uv run pytest "$@"
