# REST API

Актуальные схемы запросов и ответов доступны в публичных `/docs` и `/openapi.json`.
Данные списков защищены cookie-сессией `__Host-gl_session`; все мутации требуют
`X-Device-Id` (непустая строка после trim, до 128 символов). Источник изменения строится
из этого заголовка и не принимается в JSON. Количество возвращается как JSON number.

Для GET `/api/items` и `/api/tags` обязателен query-параметр `shopping_list_id`;
GET `/api/items` по умолчанию скрывает купленное (`include_bought=false`). POST `/api/items`,
`/api/items/quick-add`, `/api/items/bought`, `/api/items/clear-bought` требуют
`shopping_list_id` в теле. PATCH и DELETE определяют список по UUID объекта.
DELETE возвращает 204 без тела; clear-bought и bulk-tag — `{count: int}`.
Пакетные изменения атомарны. Чужие и отсутствующие объекты возвращают одинаковую ошибку 404.

GET `/api/events?shopping_list_id=<UUID>` открывает SSE-поток с той же cookie-сессией.
Авторизация завершается до отправки заголовков; ожидание событий не удерживает сессию БД.
Каждое `data:` содержит JSON сохранённого события с `type` и `payload`; события поступают
после коммита только для выбранного списка. FastAPI отправляет heartbeat каждые 15 секунд.
При отключении подписка освобождается. При подключении или восстановлении соединения клиент
перезагружает список: replay и `Last-Event-ID` не поддерживаются.

Ошибки имеют форму `{code, message, details?}`; детали валидации содержат только
`loc` и `message`. При отсутствии действующей сессии защищённые маршруты возвращают
401 до проверки заголовка устройства и схемы синтаксически корректного JSON.
Граница этого порядка — синтаксически некорректный JSON: FastAPI разбирает его
до выполнения dependency аутентификации, поэтому такой запрос возвращает 422
`invalid_request`, даже без cookie или заголовка устройства. Входные данные в ошибку
не включаются. Регрессионные тесты фиксируют этот порядок для всех item/tag маршрутов с телом.

## Персональные токены

- `GET /api/tokens` — метаданные своих PAT, включая отозванные: id, name, created_at,
  last_used_at, revoked_at. Сортировка по created_at/id.
- `POST /api/tokens` — `{name}` (после trim 1–255 символов); ответ 200 содержит метаданные
  и `token`. Это единственный ответ, в котором можно получить исходный секрет.
- `DELETE /api/tokens/{id}` — отзыв, 204. Повторный отзыв своего токена успешен;
  чужой и отсутствующий UUID дают одинаковый 404.

Мутации требуют cookie и X-Device-Id; успешные ответы имеют Cache-Control: no-store.
PAT `gl_pat_…` предназначен для MCP и не авторизует REST. Хранится только SHA-256.
Последнее использование фиксируется при успешной верификации Bearer, даже если инструмент
затем вернул ошибку. Отзыв запрещает новые HTTP-запросы; начатый вызов может завершиться.

## MCP

Streamable HTTP `/mcp` принимает `Authorization: Bearer <token>`: PAT либо OAuth access token,
без cookie. Refresh token предназначен только для `/oauth/token` и `/oauth/revoke`.
Доступны `get_shopping_list`, `list_tags`, `add_items`, `update_item`, `set_bought`,
`remove_items`. `shopping_list_id` необязателен при единственном доступном списке;
с несколькими списками передайте UUID явно. Теги фильтруются по нормализованному точному имени.
PATCH различает пропуск и null; tags=[] очищает теги. Источник берётся из PAT или
OAuth-клиента, не из аргументов инструментов.

Открытые metadata: `/.well-known/oauth-protected-resource/mcp` и корневой alias
`/.well-known/oauth-protected-resource`. Ответ 401 указывает рабочий resource_metadata.
OAuth AS: `/.well-known/oauth-authorization-server`, CIMD/DCR, PKCE и ротация refresh.
Эндпоинты согласия и подключённых приложений описаны в [OAuth](oauth.md).
`APP_PUBLIC_URL` задаёт origin без path/query/fragment/credentials; от него строится
канонный resource `/mcp`, Host/Origin allowlist и CORS. MCP не перенаправляет `/mcp` на `/mcp/`.

Payload SSE соответствует type: items_added содержит обязательные results;
операции позиций — items; tag_renamed/tags_merged — tag и previous_tag;
tag_deleted — tag. Неиспользуемые поля не передаются. Миграция 0005 переводит
существующие снимки в этот формат с сохранением полезных данных.
