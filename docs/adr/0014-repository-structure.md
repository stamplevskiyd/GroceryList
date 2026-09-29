# ADR-0014. Структура репозитория и пакетов

Статус: принято · Дата: 2026-09-29

## Контекст

Слои и правила зависимостей заданы в ADR-0001, но пишущему код нужно знать, куда класть файл.
Без зафиксированного дерева каждый новый модуль ищет себе место заново, а import-linter
(ADR-0007) требует конкретных имён пакетов.

## Решение

Дерево ниже — примерный план: имена пакетов и слоёв обязательны, отдельные файлы внутри пакета
появляются и делятся по мере надобности.

### Корень репозитория

```
GroceryList/
├── backend/                 Python-проект (uv), ниже
├── frontend/                React + Vite + vite-plugin-pwa, ниже
├── docs/                    superpowers/specs, design, adr
├── .github/workflows/       ci.yml, images.yml, deploy.yml (ADR-0015)
├── scripts/                 fmt, lint, typecheck, test, api, check (ADR-0007); deploy.sh, pg_backup.sh
├── docker-compose.yml       caddy, backend, postgres (postgres:18-alpine), backup
├── Caddyfile                статика PWA + прокси /api, /mcp, /oauth, /.well-known → backend
├── backend.Dockerfile       образ backend (uv, только API/MCP/OAuth)
├── caddy.Dockerfile         multi-stage: сборка frontend (Node) → Caddy со статикой
├── .dockerignore
├── Makefile                 тонкая обёртка над scripts/
├── .pre-commit-config.yaml
├── .env.example             все переменные Settings (ADR-0006)
├── CLAUDE.md                указатель для ассистентов: ADR, спека, scripts/check.sh
└── README.md                запуск, разработка, деплой
```

- Файлы деплоя лежат в корне: `docker compose up` работает без `-f` и из корня видит и
  `backend/`, и `frontend/` как контексты сборки.
- Локальная разработка: `docker compose up postgres` + `uv run` для бэкенда + dev-сервер Vite
  с прокси `/api`, `/mcp`, `/oauth` на бэкенд.

### Бэкенд — src-layout, пакет `grocery`

```
backend/
├── pyproject.toml, uv.lock, .python-version, alembic.ini
├── migrations/              env.py, versions/                               ADR-0013
├── src/grocery/
│   ├── __main__.py          python -m grocery create-user | export-openapi
│   ├── main.py              create_app(), lifespan: движок БД, MCP session_manager, push-воркер
│   ├── config.py            Settings, get_settings()                        ADR-0006
│   │
│   ├── api/                 ── адаптеры REST ──
│   │   ├── deps.py          authenticate, AppSourceDep, db_unit_of_work
│   │   ├── errors.py        exception handlers → ErrorResponse               ADR-0012
│   │   ├── routers/         me, items, tags, events (SSE), push, tokens, oauth_grants, auth
│   │   └── oauth/           /oauth/*, /.well-known/oauth-authorization-server, consent
│   ├── mcp_server/          ── адаптер MCP ──                                 ADR-0010
│   │   ├── server.py        MCPServer, монтирование, transport_security
│   │   ├── verifier.py      TokenVerifier SDK → services.auth.verify_bearer
│   │   ├── middleware.py    tools/call: unit_of_work, пользователь, source, ToolError
│   │   ├── tools.py         get_shopping_list, list_tags, add_items, …
│   │   └── instructions.md  инструкции сервера (спец. §6.2)
│   │
│   ├── services/            ── бизнес-логика ──                               ADR-0008
│   │   ├── shopping_list_service/   функции сервиса, merge_item, проверка доступа
│   │   ├── tags.py          переименование / объединение, массовые действия
│   │   ├── events.py        record_event, SSE-хаб, on_commit-публикация
│   │   ├── push/            worker, sender (pywebpush), тексты уведомлений
│   │   └── auth/            context (get_current_user), passwords, sessions, pats,
│   │                        rate_limit, oauth/ (authorize, tokens, clients, cimd)
│   ├── db/                  ── данные ──
│   │   ├── base.py          Base, naming_convention, миксины id / created_at  ADR-0013
│   │   ├── types.py         PydanticJSON, str_enum()
│   │   ├── session.py       unit_of_work, get_current_session, on_commit      ADR-0004
│   │   ├── models/          user, shopping_list, item, tag, event, push, auth
│   │   └── repositories/    base.py + по репозиторию на агрегат               ADR-0005
│   ├── schemas/             ── Pydantic ── items, tags, events, source, errors, auth, common
│   └── domain/              ── чистые правила ──
│       ├── normalization.py, quick_add.py
│       ├── enums.py         StrEnum: EventType, OutboxStatus, MemberRole, AddStatus
│       └── errors.py        DomainError и подклассы                          ADR-0012
└── tests/                   unit/, integration/, api/, mcp/, factories.py     ADR-0011
```

Размещение, которое легко перепутать:

- `domain/enums.py` — в нижнем слое: перечисления нужны и моделям (`db`), и схемам.
- `mcp_server/verifier.py` — в адаптере, а не в `services/auth`: он реализует интерфейс MCP SDK,
  который сервисам импортировать нельзя (ADR-0001). Проверка токена —
  `services.auth.verify_bearer`, адаптер только переводит результат в `AccessToken`.
- `merge_item` — в `services/shopping_list_service`, а не в `domain`: принимает ORM-модель `Item`.
- `api/oauth/` — HTTP-часть OAuth AS; логика — в `services/auth/oauth/`.

### Фронтенд — верхний уровень

```
frontend/
├── package.json, vite.config.ts, tsconfig.json, index.html
└── src/
    ├── api/                 openapi.json, schema.d.ts (генерируются, ADR-0009), client.ts ($api)
    ├── styles/tokens.css    копия docs/design/tokens.css
    ├── features/            list, item-sheet, tags, settings, login, consent, install-ios
    ├── components/          общие элементы UI
    ├── lib/                 device-id, sse, push-подписка
    └── sw.ts                service worker: оболочка приложения + обработка push
```

Детали фронтенда (роутер, менеджер пакетов, состояние) фиксируются в плане реализации фронтенда.

### Организация по слоям, а не по фичам

Код раскладывается по слоям (`api/routers/items.py`, `services/shopping_list_service/`,
`db/repositories/items.py`), а не по фичам (`items/` с роутером, сервисом и репозиторием).
Слои прямо следуют ADR-0001 и проверяются import-linter одним контрактом `layers`; фича при
этом занимает 4–5 папок — при нашем объёме это приемлемо.

## Последствия

- Для любого нового файла место определяется слоем: сначала «какой это слой», потом «какая сущность».
- Контракт import-linter записывается прямо по именам пакетов из этого дерева.

## Как проверяется

- `import-linter` (контракт `layers`: `grocery.api | grocery.mcp_server` → `grocery.services` →
  `grocery.db` → `grocery.schemas` → `grocery.domain`, плюс запреты из ADR-0001) в `scripts/lint.sh`.
- Ревью: новый пакет верхнего уровня в `grocery/` — только с правкой этого ADR.
