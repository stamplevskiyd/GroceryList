# GroceryList

PWA-список покупок с MCP-сервером: ассистент (Claude, ChatGPT, Codex) добавляет ингредиенты,
приложение обновляется вживую и присылает push.

- Что делает система — [спецификация](docs/superpowers/specs/2026-09-29-grocery-list-design.md)
- Как устроен код — [ADR](docs/adr/README.md)
- План работ — [docs/superpowers/plans](docs/superpowers/plans/README.md)

## Разработка

Нужны [uv](https://docs.astral.sh/uv/) ≥ 0.12 и Docker.

```bash
cp .env.example .env
docker compose up -d postgres
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn grocery.main:create_app --factory --reload
```

Если порт 5432 занят, задайте в `.env` `POSTGRES_PORT` и тот же порт в `DB_URL`.

Проверка: `curl localhost:8000/api/health` → `{"status":"ok","version":"dev"}`.

Хуки перед коммитом (один раз): `cd backend && uv run pre-commit install`.

## Проверки

Все команды — в `scripts/`, Makefile их только вызывает (ADR-0007):

| Команда | Что делает |
|---|---|
| `make fmt` | форматирование и автоисправления ruff |
| `make lint` | ruff, границы слоёв (import-linter), shellcheck |
| `make typecheck` | mypy strict |
| `make test` / `scripts/test.sh unit` | все тесты / только быстрые, без Docker |
| `make check` | всё вместе; код готов, когда она зелёная |

Интеграционные тесты сами поднимают Postgres в Docker (testcontainers).
