# GroceryList

PWA-список покупок с MCP-сервером: ассистент (Claude, ChatGPT, Codex) добавляет ингредиенты,
приложение обновляется вживую и присылает push.

- Что делает система — [спецификация](docs/superpowers/specs/2026-09-29-grocery-list-design.md)
- Как устроен код — [ADR](docs/adr/README.md)
- План работ — [docs/superpowers/plans](docs/superpowers/plans/README.md)

## Разработка

Нужны [uv](https://docs.astral.sh/uv/) ≥ 0.12, Docker и Node.js 22 с npm.

```bash
cp .env.example .env
npm ci --prefix frontend
docker compose up -d postgres
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn grocery.main:create_app --factory --reload
```

Если порт 5432 занят, задайте в `.env` `POSTGRES_PORT` и тот же порт в `DB_URL`.

Проверка: `curl localhost:8000/api/health` → `{"status":"ok","version":"dev"}`.

Хуки перед коммитом (один раз): `cd backend && uv run pre-commit install`.

Первичный пользователь (публичной регистрации нет):

```bash
cd backend
uv run python -m grocery create-user anna
```

Команда дважды запрашивает пароль скрытым вводом, сохраняет Argon2-хеш и атомарно создаёт
список «Покупки» с владельцем. Перед запуском примените миграции (`uv run alembic upgrade head`).

Реализован домен списка: нормализация и быстрый ввод, объединение позиций, теги, купленное,
история событий и публикация после коммита во внутренний SSE-хаб. Доступны cookie-вход
и [REST API позиций и тегов с SSE-обновлениями](docs/api.md). PWA и подключение ассистентов
идут последующими этапами плана.

Cookie-сессии всегда `Secure`, `HttpOnly`, `SameSite=Lax`. Для ручного входа и запросов
с cookie используйте HTTPS base URL (тестовый хост либо локальный HTTPS-прокси),
cookie jar и `X-Device-Id` на всех мутациях. Публичный health доступен и по HTTP.

OpenAPI и типы TypeScript сохранены в `frontend/src/api/`. После изменения API выполните
`make api` и сохраните оба файла. Генерация работает без Docker, БД и запуска приложения:

```bash
make api
scripts/api.sh --check
APP_PUBLIC_URL=http://localhost \
  DB_URL=postgresql+asyncpg://unused:unused@127.0.0.1:1/unused \
  uv run --project backend python -m grocery export-openapi --output /tmp/openapi.json
```

Без `--output` команда выводит только JSON в stdout. Экспорт использует версию Python-пакета,
поэтому `APP_VERSION` не меняет контракт. Проверка `--check` сравнивает оба артефакта
с новой генерацией во временной директории и не перезаписывает сохранённые файлы.
Сейчас frontend содержит только инструменты контракта; React/PWA добавятся на этапе 7.

## Проверки

Все команды — в `scripts/`, Makefile их только вызывает (ADR-0007):

| Команда | Что делает |
|---|---|
| `make fmt` | форматирование и автоисправления ruff |
| `make lint` | ruff, границы слоёв (import-linter), shellcheck |
| `make typecheck` | mypy strict и TypeScript strict |
| `make api` / `scripts/api.sh --check` | генерация / проверка актуальности OpenAPI и TS |
| `make test` / `scripts/test.sh unit` | все тесты / только быстрые, без Docker |
| `make check` | всё вместе; код готов, когда она зелёная |

Интеграционные тесты сами поднимают Postgres в Docker (testcontainers).
