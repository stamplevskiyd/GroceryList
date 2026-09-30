#!/usr/bin/env bash
# Офлайн-экспорт и проверка обоих артефактов контракта (ADR-0009).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--check" ) ]]; then
  echo "Использование: scripts/api.sh [--check]" >&2
  exit 2
fi

generate() {
  APP_PUBLIC_URL=http://localhost \
    DB_URL=postgresql+asyncpg://unused:unused@127.0.0.1:1/unused \
    uv run --project "$root/backend" python -m grocery export-openapi --output "$1/openapi.json"
  "$root/frontend/node_modules/.bin/openapi-typescript" "$1/openapi.json" -o "$1/schema.d.ts"
}

if [[ "${1:-}" == "--check" ]]; then
  temporary="$(mktemp -d)"
  trap 'rm -rf "$temporary"' EXIT
  generate "$temporary"
  for artifact in openapi.json schema.d.ts; do
    if ! cmp -s "$temporary/$artifact" "$root/frontend/src/api/$artifact"; then
      echo "Выполните scripts/api.sh и сохраните контракт: $artifact" >&2
      exit 1
    fi
  done
else
  mkdir -p "$root/frontend/src/api"
  generate "$root/frontend/src/api"
fi
