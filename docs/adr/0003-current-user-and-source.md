# ADR-0003. Текущий пользователь в контексте, источник изменения — явным аргументом

Статус: принято · Дата: 2026-09-29

## Контекст

Каждой операции нужно знать три вещи:

- **кто пользователь** — для проверки доступа к списку;
- **с каким списком** работаем;
- **откуда пришло изменение** (источник, `source`) — чтобы не слать push на устройство-источник,
  подписать позицию «добавил Claude» и сформировать текст уведомления (спец. §3.2, §7).

Учётные данные приходят по-разному: cookie-сессия + `X-Device-Id` в REST,
`Authorization: Bearer` (OAuth access token или PAT) в MCP.

## Решение

### Пользователь — ORM-модель `User` в `ContextVar`

- `get_current_user() -> User` возвращает ORM-модель пользователя, загруженную в текущем
  `unit_of_work` (ADR-0004). Вне аутентифицированного контекста — `AuthError`.
- Выставляет его только аутентификация:
  - **REST**: async-dependency `authenticate` на уровне роутера
    (`APIRouter(dependencies=[Depends(authenticate)])`) — проверяет cookie-сессию. Эндпоинты
    пользователя в параметрах не объявляют. Публичные маршруты (логин, OAuth, metadata,
    VAPID-ключ) — в отдельном роутере без этой dependency.
  - **MCP**: токен проверяет верификатор SDK (ADR-0010), а middleware `MCPServer` на `tools/call`
    загружает пользователя по `get_access_token().subject` и выставляет его в контекст.
  - **Тесты**: контекстный менеджер `acting_as(user)`.
- Разрешение учётных данных — функции `auth`, не зависящие от транспорта:
  `resolve_session(token) -> User` для cookie и `verify_bearer(token) -> AccessToken` для MCP
  (OAuth access token или PAT; claims содержат `client_id` и `client_name` для `McpSource`).

### Список — явно, в данных запроса

- `shopping_list_id` передаётся явно в схеме операции (`AddItems.shopping_list_id`, параметр запроса и т. п.).
  PWA узнаёт свои списки из `GET /api/me`.
- Раз `shopping_list_id` приходит от клиента, **каждая операция сервиса начинается с проверки доступа**:
  `ensure_shopping_list_access(shopping_list_id)` — текущий пользователь есть в `shopping_list_members` этого списка,
  иначе `NotFoundError` (не раскрываем существование чужого списка).
- Операции по `id` позиции или тега (`update_item`, `set_bought`) проверяют доступ к списку
  найденного объекта через общий хелпер сервиса, а не вручную в каждом методе.
- MCP: `shopping_list_id` в инструментах необязателен; если не передан — берётся
  единственный список пользователя. Ассистенту не нужно сначала узнавать id.

### Источник — схема `Source`, явным аргументом сервиса

```python
class AppSource(BaseModel):
    kind: Literal["app"] = "app"
    device_id: str                 # из заголовка X-Device-Id

class McpSource(BaseModel):
    kind: Literal["mcp"] = "mcp"
    client_id: str                 # OAuth client_id или id PAT
    client_name: str               # «Claude», «ChatGPT» — из регистрации клиента; для PAT — его имя

Source = Annotated[AppSource | McpSource, Field(discriminator="kind")]
```

- Источник **никогда не берётся из тела запроса** — иначе клиент подделает его (ассистент
  «притворится» телефоном, и push уйдёт не туда). Его строит адаптер из данных аутентификации:
  - REST: dependency `AppSourceDep` читает `X-Device-Id`;
  - MCP: `get_mcp_source()` из проверенного токена.
- Мутирующие функции сервиса принимают `source: Source` **явным аргументом**:
  `shopping_list_service.add_items(data, source)`.
- Pydantic (а не dataclass), потому что источник сохраняется в `jsonb`: `items.sources`,
  `events.source`.

## Последствия

- Сигнатура эндпоинта показывает только данные операции и источник; пользователь неявный,
  как сессия, но выставляется в одном месте на роутер.
- Добавление внешнего IdP меняет `auth`, но не эндпоинты и не сервисы.
- Несколько списков в UI не потребуют изменений в сервисах: `shopping_list_id` уже приходит явно.

## Как проверяется

- Тест: обход `app.routes` — каждый маршрут, кроме явного списка публичных, находится под
  `authenticate` (запрос без cookie → 401).
- Тест изоляции для каждой операции сервиса: `shopping_list_id` или `id` объекта чужого списка → `NotFoundError`.
- Тесты MCP: вызов без токена, с отозванным PAT, с просроченным access token → ошибка.
- Ревью: `Source` не встречается в схемах тела запроса.
