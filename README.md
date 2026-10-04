# GroceryList

PWA-список покупок с MCP-сервером: ассистент (Claude, ChatGPT, Codex) добавляет ингредиенты,
приложение обновляется вживую и присылает push.

- Что делает система — [спецификация](docs/superpowers/specs/2026-09-29-grocery-list-design.md)
- Как устроен код — [ADR](docs/adr/README.md)
- План работ — [docs/superpowers/plans](docs/superpowers/plans/README.md)
- CI/CD, подготовка VPS и откат — [инструкция по деплою](docs/deployment.md)

## Разработка

Нужны [uv](https://docs.astral.sh/uv/) ≥ 0.12, Docker и Node.js ≥ 22.12 с npm.

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

Пользователь может зарегистрироваться на странице входа кнопкой
«Нет аккаунта? Зарегистрироваться»: логин, пароль (8–128 символов) и подтверждение.
После регистрации он автоматически входит и получает личный список «Покупки».
Создание пользователя через CLI также доступно:

```bash
cd backend
uv run python -m grocery create-user anna
```

Команда дважды запрашивает пароль скрытым вводом, сохраняет Argon2-хеш и атомарно создаёт
список «Покупки» с владельцем. Перед запуском примените миграции (`uv run alembic upgrade head`).

Реализован домен списка: нормализация и быстрый ввод, объединение позиций, теги, купленное,
история событий и публикация после коммита во внутренний SSE-хаб. Доступны cookie-вход
и [REST API позиций и тегов с SSE-обновлениями](docs/api.md). MCP `/mcp` принимает PAT
и OAuth access tokens. Реализованы [OAuth-сервер и экран согласия](docs/oauth.md);
добавлен минимальный интерфейс списка: вход, быстрый ввод, купленное, удаление,
фильтр, группировка и управление тегами, живые обновления и карточка редактирования покупки.
Установка PWA и настройки — впереди.
Состояние опубликованного релиза — в инструкции по деплою;
публичный адрес — **https://grocery.94-159-101-162.sslip.io**,
[Swagger](https://grocery.94-159-101-162.sslip.io/docs), [статус деплоя](docs/deployment.md).

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
Frontend — React с типизированным клиентом openapi-fetch и TanStack Query.
На `/` находятся вход и список покупок, на `/consent` — согласие OAuth.
Минимальный сценарий проверки — [этап 7](docs/superpowers/plans/2026-10-04-07-shopping-ui.md).

### Интерфейс и Caddy

Запустить frontend локально (API проксируется на backend `localhost:8000`):

```bash
npm run dev --prefix frontend
```

Откройте адрес из вывода Vite (обычно `http://127.0.0.1:5173`). Пока это статическая
страница «Готовим приложение», без входа и операций со списком. Проверить вручную:
широкое и узкое окно, светлая и тёмная темы, отсутствие горизонтального скролла.

Образ `caddy.Dockerfile` собирает страницу через Vite и раздаёт её из Caddy.
Профиль `runtime` включает Caddy; `/api`, `/mcp`, `/oauth`, `/.well-known`, Swagger
и OpenAPI проксируются на backend с сохранением пути. Остальные страницы используют
SPA fallback; отсутствующие `/assets/*` возвращают 404. Ответы API и SSE не попадают
под SPA fallback; прокси передаёт поток без буферизации.

Для полного runtime локально задайте `APP_PUBLIC_URL=https://localhost:8443` в `.env`.
Caddy слушает loopback на 8080/8443; локальный сертификат остаётся в Docker-volume.
Системное доверие к сертификатам автоматически не настраивается. Safari для входа
требует HTTPS с доверенным сертификатом; HTTP-предпросмотр выше проверяет только статику.
На VPS задайте `CADDY_BIND=0.0.0.0`, `CADDY_HTTP_PORT=80`, `CADDY_HTTPS_PORT=443`
и `APP_PUBLIC_URL=https://ваш-домен`. При доступном домене Caddy получает публичный
сертификат автоматически. Порт URL должен соответствовать порту выбранного протокола.

Ручная приёмка полного окружения: открыть `/`, обновить вложенный адрес `/settings`,
открыть `/docs`, выполнить login → `/api/me`; проверить MCP и получение SSE после
изменения списка. Успешная сборка не заменяет эту проверку в браузере.

## MCP и PAT

После миграций и входа по cookie выдайте PAT через `POST /api/tokens` с телом
`{"name":"Claude Code"}` и заголовком `X-Device-Id`. Сохраните поле `token` из ответа:
оно показывается только при выдаче. `GET /api/tokens` возвращает метаданные,
`DELETE /api/tokens/{id}` отзывает токен.

MCP-клиент подключается к `<APP_PUBLIC_URL>/mcp`, передавая
`Authorization: Bearer <PAT>`. Шесть инструментов используют тот же сервис списка,
что REST; ошибки откатывают изменения, коммит публикует события в SSE.
`APP_PUBLIC_URL` должен быть origin (например, `https://grocery.example`) без пути.
OAuth-подключение использует тот же `/mcp`: [протокол и ручная проверка](docs/oauth.md).
Подключение реальных Claude/ChatGPT остаётся ручной приёмкой после обновления сервера.

`APP_LOG_LEVEL` принимает DEBUG, INFO, WARNING, ERROR или CRITICAL и применяется
при старте к приложению и MCP. После обновления выполните `alembic upgrade head`:
миграция 0005 обновляет формат ранее сохранённых payload событий, 0006 добавляет OAuth.

## Проверки

Все команды — в `scripts/`, Makefile их только вызывает (ADR-0007):

| Команда | Что делает |
|---|---|
| `make fmt` | форматирование и автоисправления ruff |
| `make lint` | ruff, границы слоёв и сервисов (import-linter), запрет commit/rollback вне UoW, shellcheck, actionlint |
| `make typecheck` | mypy strict и TypeScript strict |
| `make api` / `scripts/api.sh --check` | генерация / проверка актуальности OpenAPI и TS |
| `make test` / `scripts/test.sh unit` | все тесты / только быстрые, без Docker |
| `make check` | всё вместе; код готов, когда она зелёная |

Интеграционные тесты сами поднимают Postgres в Docker (testcontainers).

## Контейнер backend и бэкапы (этап 5)

Образ backend и бэкапы проверены; Caddy, статика и CI/CD работают на VPS. GitHub Actions
собрал, опубликовал и развернул `v0.5.0`; публичная регистрация, HTTPS, cookie-вход, редактирование и операции списка,
PAT, MCP и SSE через Caddy проверены. Ручная приёмка нового интерфейса —
в [плане этапа 7](docs/superpowers/plans/2026-10-04-07-shopping-ui.md).
После создания `.env` из `.env.example`:

```bash
docker compose --profile runtime up -d --build
curl localhost:8000/api/health
docker compose exec backend python -m grocery create-user anna
```

Backend перед запуском применяет Alembic-миграции; ошибка миграции завершает контейнер.
`APP_VERSION` зашивается в `/app/VERSION` при сборке из `IMAGE_TAG`; entrypoint читает
его перед запуском, поэтому `.env` не может подменить версию контейнера. Для Python на хосте
используется `DB_URL`, внутри контейнера — `CONTAINER_DB_URL`. Если меняете реквизиты
Postgres, обновите оба URL; пароль в URL должен быть URL-encoded. Порт backend доступен
только на localhost. Внешние запросы проходят через Caddy; настройки адреса описаны выше.

Backup сохраняет custom-format архивы в volume `postgres-backups` каждые
`BACKUP_INTERVAL_SECONDS` (по умолчанию сутки), оставляя `BACKUP_KEEP` последних копий.
Незавершённый dump не публикуется и не запускает удаление старых копий. Копия вручную:

```bash
docker compose --profile runtime run --rm backup manual
```

Восстановление проверяйте в отдельную пустую БД, подставив имя архива, выведенное backup:

```bash
docker compose exec postgres sh -c 'createdb -U "$POSTGRES_USER" grocery_restored'
docker compose --profile runtime run --rm --entrypoint pg_restore backup \
  --exit-on-error --single-transaction --no-owner --no-acl \
  --dbname=grocery_restored /backups/ИМЯ_АРХИВА.dump
```

Для переключения приложения на восстановленную БД измените `CONTAINER_DB_URL` и
пересоздайте backend. Volume на VPS не защищает от потери самого VPS: перед эксплуатацией
нужно настроить копирование архивов за его пределы. После аварийного завершения backup
может остаться `/backups/.backup-lock`: удаляйте его только убедившись, что dump не выполняется.

Воспроизводимая проверка образа и backup/restore в изолированных Docker-ресурсах:

```bash
docker build -f backend.Dockerfile --build-arg APP_VERSION=stage5-check \
  -t grocerylist-backend:stage5-check .
scripts/check_runtime.sh grocerylist-backend:stage5-check
```

Smoke проверяет миграции, health/version, retention, ошибку dump и восстановление данных.
При выходе удаляет только созданные им контейнеры, сеть и backup-volume.
