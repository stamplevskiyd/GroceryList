# REST API и вход в PWA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Выполнение завершено 2026-09-30; результаты и принятые уточнения записаны ниже.

**Goal:** Предоставить проверенный HTTP-контракт для PWA: вход/выход, текущий пользователь, позиции, теги, живые обновления и генерируемые TypeScript-типы.

**Architecture:** REST остаётся тонким адаптером над готовым `shopping_list_service`. Сессии и вход добавляются в `services/auth`; аутентификация выставляет пользователя в ContextVar внутри того же UoW, что и операция. SSE проверяет сессию и доступ до отправки HTTP-заголовков, закрывает UoW и затем читает существующий хаб без удержания соединения БД.

**Tech Stack:** Python 3.14, FastAPI ≥ 0.142, Pydantic ≥ 2.13, SQLAlchemy ≥ 2.1.1 async, Alembic ≥ 1.20, Postgres 18, argon2-cffi, pytest/httpx/testcontainers. Для контракта: Node 22, npm, openapi-typescript 7.13.0 и TypeScript 5.9.3 с lockfile.

**Spec:** `docs/superpowers/specs/2026-09-29-grocery-list-design.md`, §3.2, §4 (sessions), §5–7, §9, §11. Обязательные решения: ADR-0002–0009, ADR-0010 (только пароли/cookie/rate limit), ADR-0011–0014.

## Global Constraints

- «Весь бэкенд — один процесс»: лимитер входа и SSE-хаб находятся в памяти; Redis не добавляется.
- «Количество — число в JSON»: внутри системы Decimal, на выходе JSON number (ADR-0009).
- «Одна схема — одно направление»: Create/Update только на входе, Read только на выходе.
- `Source` не принимается в теле запроса. AppSource строится из обязательного для мутаций `X-Device-Id`.
- Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`; в таблице sessions только SHA-256 токена.
- `get_current_user()` возвращает User, загруженного внутри текущего UoW; ORM не возвращается из HTTP-эндпоинтов.
- Коммит только в `unit_of_work`, до отправки обычного HTTP-ответа (`scope="function"`).
- SSE: встроенный `fastapi.sse.EventSourceResponse`, heartbeat каждые 15 секунд; поток не держит сессию БД.
- Каждая операция с чужими объектами неотличима от операции с отсутствующими: 404.
- Пакетные мутации атомарны; один вызов сервиса — одно событие. Не переносить бизнес-логику в роутеры.
- Python 3.14, `uuid.uuid7`, `Numeric`/Decimal, timezone-aware даты, enum как VARCHAR(32), lazy="raise".
- Готовность: `scripts/check.sh` зелёный, включая Postgres, stairway и проверку актуальности API-артефактов.

## Граница этапа и исходное состояние

Исходный коммит домена: `39ce2bf`. Есть 113 тестов, модели/миграции 0001–0002, CLI `create-user`, ContextVar пользователя, `Repository`, нормализация, операции списка, `record_event`, `event_hub`. Есть только публичный `/api/health`.

В этот этап входят login/logout/me, REST списка и тегов, SSE, обработчики ошибок, экспорт OpenAPI и TypeScript-контракт. PAT/MCP — этап 4; OAuth — этап 6; React/PWA/UI — этап 7; push/outbox — этап 8. Минимальный `frontend/package.json` в этом этапе нужен только для генератора и проверки типов контракта.

Перед исполнением: прочитать CLAUDE.md, спецификацию и ADR; `git status --short`; использовать рабочую ветку согласно выбранному Superpowers workflow; `scripts/check.sh` должен подтвердить исходные 113 тестов. Не переписывать готовый домен ради адаптеров.

## Решения, уточнённые этим планом

1. Сессия живёт 30 дней без скользящего продления; `AUTH_SESSION_TTL_SECONDS=2592000`. Cookie `__Host-gl_session`, `Path=/`, без Domain, Secure всегда. Новое устройство/повторный вход получают новый токен; старый действителен до logout/expiry. Login не доверяет существующей cookie и не переиспользует её. Logout отзывает только текущую сессию.
2. Device id — непустая строка после trim, до 128 символов. Она задаёт источник изменения, но не является вторым фактором: сессия не привязывается к соответствию каждого последующего заголовка исходному device id.
3. Лимитер: максимум 5 попыток на username и 30 на IP за 300 секунд. Считаются все допущенные попытки, включая успешные; успешный вход не сбрасывает счётчик. Используются независимые ключи IP и username, а не пара `(IP, username)`. Ограничение резервируется до await/Argon2, чтобы параллельные запросы не обходили лимит.
4. Лимиты и время окна — настройки `AUTH_LOGIN_USERNAME_LIMIT=5`, `AUTH_LOGIN_IP_LIMIT=30`, `AUTH_LOGIN_WINDOW_SECONDS=300`. Время лимитера — monotonic; expiry сессии — UTC. Ограничить память 10000 активных ключей, удалять истёкшие; при заполнении не вытеснять активные ключи и не пропускать новых без учёта, а отвечать 429 до ближайшего освобождения.
5. IP берётся из `request.client.host`, не из произвольного `X-Forwarded-For`. Доверенные proxy/forwarded hosts Uvicorn настраиваются при деплое на этапе 5; сам REST не парсит эти заголовки.
6. Login принимает JSON `{username, password}`, требует X-Device-Id, возвращает MeRead и устанавливает cookie. Logout требует действующую cookie и X-Device-Id, возвращает 204 и удаляет cookie с теми же Path/Secure/SameSite. Повторный logout без сессии — 401.
7. Для чтения списка/тегов/events shopping_list_id — обязательный query-параметр. Для add/quick-add/bought/clear-bought — поле JSON. PATCH/DELETE объектов определяют список по id через существующий сервис.
8. DELETE возвращает 204 без тела; clear-bought и bulk-tag — `{count: int}`. Add — 200 с результатом для каждого элемента, так как пакет может одновременно создавать и объединять. PATCH — 200 с обновлённым объектом.
9. SSE использует обычные `data:` сообщения с JSON-событием, discriminated по `type`. Replay и обработку Last-Event-ID не добавлять: PWA при установлении/восстановлении соединения перезагружает данные. Сессия проверяется при каждом новом соединении; PWA закроет поток при logout на этапе 7.
10. Генерация контракта работает без PostgreSQL и без запуска lifespan. APP_VERSION не меняет сохранённый контракт: экспорт использует версию Python-пакета. OpenAPI формат FastAPI сохраняется; не переписывать SSE `itemSchema` для удобства генератора.

## HTTP-контракт

У всех protected маршрутов OpenAPI security `SessionCookie` (`apiKey`, in=cookie, name=__Host-gl_session). Публичные: `/api/health`, `/api/auth/login`, `/docs`, `/redoc`, `/openapi.json`. Документация публична, данные — нет. CORS для cross-origin cookie-запросов не включать: будущая PWA обслуживается с того же origin.

| Метод и путь | Вход | Успех | Сервис |
|---|---|---|---|
| POST /api/auth/login | LoginCreate + X-Device-Id | 200 MeRead + Set-Cookie | auth.login |
| POST /api/auth/logout | cookie + X-Device-Id | 204 + удаление cookie | auth.logout |
| GET /api/me | cookie | 200 MeRead | auth.get_me |
| GET /api/items | shopping_list_id, include_bought=false | 200 list[ItemRead] | get_items |
| POST /api/items | AddItems | 200 list[AddItemResult] | add_items |
| POST /api/items/quick-add | QuickAdd | 200 QuickAddResult | quick_add |
| PATCH /api/items/{id} | ItemUpdate | 200 ItemRead | update_item |
| DELETE /api/items/{id} | id | 204 | delete_item (новая обёртка сервиса) |
| POST /api/items/bought | SetBought | 200 list[ItemRead] | set_bought |
| POST /api/items/clear-bought | ClearBought | 200 CountRead | clear_bought |
| GET /api/tags | shopping_list_id | 200 list[TagUsageRead] | list_tags |
| PATCH /api/tags/{id} | TagUpdate | 200 TagRead | rename_tag |
| DELETE /api/tags/{id} | id | 204 | delete_tag |
| POST /api/tags/{id}/bulk | TagBulk | 200 CountRead | bulk_tag |
| GET /api/events | shopping_list_id + cookie | 200 text/event-stream | authorize_events + event_hub |

Все мутации требуют X-Device-Id. Missing/empty/too-long header — 422 ErrorResponse. На protected route аутентификация выполняется до проверки заголовка и схемы синтаксически корректного JSON: без действующей cookie — 401, даже если X-Device-Id отсутствует. Синтаксически некорректный JSON транспортный парсер FastAPI отклоняет раньше аутентификации с 422 `invalid_request`. Login — публичный, но заголовок проверяется.

PROTECTED_RESPONSES после Task 4 включает 401/404/409/422/500; PUBLIC_RESPONSES для login — 401/422/429/500. Обе карты используют `{"model": ErrorResponse}` и соответствующие описания; это центральное место объявления схем ошибок для роутеров. Для SSE производная карта `SSE_PROTECTED_RESPONSES` сохраняет статусы/описания и явно задаёт `application/json` со ссылкой на общий ErrorResponse, чтобы response class не описывал ошибки как поток.

Общие ошибки: 401 `not_authenticated` либо `invalid_credentials`; 404 — code из DomainError; 409 `conflict`; 422 `invalid_request` (валидация HTTP) либо `invalid_input` (сервис); 429 `too_many_attempts` + целый Retry-After ≥ 1; 500 `internal_error`. Форма `{code, message, details?}`, details — только `{loc: list[str | int], message: str}`. Не возвращать `hint`, пароль, входное значение, SQL или traceback.

## Карта файлов

- `schemas/common.py`: Quantity с JSON-сериализацией и CountRead.
- `schemas/auth.py`: LoginCreate, SessionCreate, SessionIssued, ShoppingListRead, MeRead.
- `schemas/errors.py`: ErrorResponse, использует существующий domain.errors.ErrorDetail.
- `schemas/items.py`: переиспользование Quantity, SetBought/ClearBought; сохранить computed_field и PATCH semantics.
- `schemas/tags.py`: TagBulk; `schemas/events.py`: типизированные выходные варианты SSE и корневая схема.
- `db/models/auth.py`, `db/repositories/sessions.py`, миграция 0003: sessions.
- `services/auth/context.py`, `passwords.py`, `sessions.py`, `rate_limit.py`, `__init__.py`: разделить контекст/пароли/сессии без изменения старых импортов.
- `api/errors.py`, `api/deps.py`, `api/routers/auth.py`, `me.py`, `items.py`, `tags.py`, `events.py`.
- `services/shopping_list_service/__init__.py`: только новая функция удаления по id.
- `__main__.py`: export-openapi без настройки движка; `main.py`: подключение роутеров и ошибок.
- `scripts/api.sh`, `scripts/check.sh`, `scripts/typecheck.sh`, `Makefile`, `.github/workflows/ci.yml`, `.env.example`, `README.md`.
- `frontend/package.json`, `package-lock.json`, `tsconfig.json`, `src/api/openapi.json`, `src/api/schema.d.ts`, `tests/api-contract.ts`: только инструментальный контракт, без приложения.

## Task 1. Общие ошибки и JSON-контракт

**Files:** Create `backend/src/grocery/schemas/common.py`, `schemas/errors.py`, `api/errors.py`. Modify `schemas/items.py`, `main.py`. Test `backend/tests/unit/test_api_schemas.py`, `backend/tests/api/test_errors.py`.

**Consumes:** DomainError/NotFoundError/InvalidInputError/ConflictError, ErrorDetail, ItemRead, ParsedItem; create_app().
**Produces:** Quantity с Decimal внутри и number в JSON; ErrorResponse; `register_error_handlers(app: FastAPI) -> None`; полные 422/500 ответы и reusable responses mapping.

- [x] **1. Написать тесты контракта:** Decimal остаётся точным до сериализации; ItemRead/ParsedItem.quantity, AddItemResult.item.quantity и EventPayload.items.quantity в JSON — число или null. На тестовых probe routes проверить DomainError statuses, отсутствие hint/input/password и форму RequestValidationError. Ошибку коммита existing probe route проверить как 500 в той же схеме; для неожиданных исключений HTTP-клиент использует ASGITransport(raise_app_exceptions=False), потому что Starlette после отправки error response может повторно поднять исключение.

  ```python
  from decimal import Decimal
  from grocery.schemas.items import ParsedItem

  def test_quantity_is_json_number() -> None:
      parsed = ParsedItem(name="Лук", quantity=Decimal("1500"), unit="г")
      assert parsed.quantity == Decimal("1500")
      assert parsed.model_dump(mode="json")["quantity"] == 1500.0
  ```

  ```python
  async def test_validation_does_not_echo_password(client: httpx.AsyncClient) -> None:
      response = await client.post("/probe/validate", json={"password": "private-test-value"})
      assert response.status_code == 422
      assert response.json()["code"] == "invalid_request"
      assert "private-test-value" not in response.text
  ```

  Probe `/probe/validate` определить в тесте с обязательным дополнительным полем; не добавлять probe endpoints в приложение.

- [x] **2. Убедиться в RED:** `scripts/test.sh tests/unit/test_api_schemas.py tests/api/test_errors.py`. Причина — текущий Decimal сериализуется строкой, обработчиков нет.
- [x] **3. Реализовать тип и обработчики:**

  ```python
  Quantity = Annotated[
      Decimal,
      PlainSerializer(float, return_type=float, when_used="json"),
  ]
  PositiveQuantity = Annotated[Quantity, Field(gt=0, allow_inf_nan=False)]

  class ErrorResponse(BaseModel):
      code: str
      message: str
      details: list[ErrorDetail] | None = None

  class CountRead(BaseModel):
      count: int = Field(ge=0)
  ```

  Create/Update используют PositiveQuantity, Read/ParsedItem — Quantity. Field constraints исходного входа сохранить. Установка serializer не меняет Numeric или арифметику. Error handler DomainError использует `str(exc)` (учитывает уточнённое сообщение), `exc.code`, `exc.details`; маппинг по базовому классу, info log только code. Handler RequestValidationError переносит `loc` и `msg`, исключает `input/ctx`. Handler Exception логирует traceback на error, клиенту фиксированное сообщение. Ответ через JSONResponse, `exclude_none=True`; status mappings 404/422/409. Auth handlers добавить в Task 4 после определения исключений.
- [x] **4. Проверить GREEN:** targeted tests + `scripts/typecheck.sh`; существующие domain/merge tests остаются зелёными.
- [x] **5. Commit:** `git add backend/src/grocery/schemas backend/src/grocery/api/errors.py backend/src/grocery/main.py backend/tests/unit/test_api_schemas.py backend/tests/api/test_errors.py && git commit -m 'feat: define REST error and quantity contract'`.

## Task 2. Cookie-сессии и сервис входа

**Files:** Create `schemas/auth.py`, `db/models/auth.py`, `db/repositories/sessions.py`, `services/auth/context.py`, `services/auth/passwords.py`, `services/auth/sessions.py`, `services/auth/errors.py`, revision `0003`. Modify `services/auth/__init__.py`, `config.py`, `db/models/__init__.py`, `.env.example`. Test `tests/integration/test_auth_sessions.py`, `tests/unit/test_passwords.py`, existing migration/context/CLI tests.

**Consumes:** user_repo.by_username/get, shopping_list_repo.for_user, acting_as/get_current_user, Repository, unit_of_work, Settings.
**Produces:**

```python
async def issue_session(user_id: UUID, device_id: str) -> SessionIssued: ...
async def resolve_session(token: str) -> User: ...
async def logout(token: str) -> None: ...
async def get_me() -> MeRead: ...
async def verify_password(password: str, password_hash: str | None) -> bool: ...
```

`SessionIssued` содержит token/UTC expires_at; сервисы наружу возвращают схемы, исключение `resolve_session` намеренно возвращает User для аутентификации (ADR-0003).

- [x] **1. Написать тесты сохранения и expiry:** выданный token не равен token_hash, token_hash равен SHA-256; resolve загружает правильного пользователя; неизвестный/пустой/просроченный token — AuthError; logout удаляет строку и делает token непригодным; get_me содержит только id/username/shopping_lists. Два устройства получают разные сессии, logout первой не удаляет вторую. Исключение UoW после issue_session откатывает session.

  ```python
  async def test_session_stores_only_hash(owner: User) -> None:
      async with unit_of_work() as db:
          issued = await issue_session(owner.id, "phone")
          stored = await db.scalar(select(Session))
          assert stored is not None
          assert stored.token_hash == hashlib.sha256(issued.token.encode()).hexdigest()
          assert stored.token_hash != issued.token
          assert stored.expires_at.tzinfo is not None
      async with unit_of_work():
          assert (await resolve_session(issued.token)).id == owner.id
  ```

  Для expiry присвоить expires_at прошлом в отдельном UoW и затем resolve в новом UoW. Для паролей: правильный/неправильный пароль; неизвестный пользователь выполняет Argon2 verify dummy hash той же сложности, не short-circuit. Повреждённый сохранённый hash — внутренний сбой, не «успешный вход».

- [x] **2. RED:** `scripts/test.sh tests/integration/test_auth_sessions.py tests/unit/test_passwords.py`.
- [x] **3. Реализовать schemas/model/repo:**

  ```python
  class SessionCreate(BaseModel):
      user_id: UUID
      token_hash: str
      expires_at: datetime
      device_id: str

  class SessionIssued(BaseModel):
      token: str
      expires_at: datetime

  class ShoppingListRead(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      id: UUID
      name: str

  class MeRead(BaseModel):
      id: UUID
      username: str
      shopping_lists: list[ShoppingListRead]
  ```

  `Session(Entity)` таблица `sessions`, FK user_id CASCADE + index, String(64) token_hash unique, DateTime(timezone=True) expires_at + index, String(128) device_id. `SessionRepository(Repository[Session, SessionCreate, BaseModel])`: `by_token_hash(token_hash: str) -> Session | None`. Токен `"gl_sess_" + secrets.token_urlsafe(32)`, hash SHA-256 через общий `token_hash(token: str) -> str` в sessions.py (в дальнейшем переиспользовать для PAT). resolve проверяет `expires_at <= datetime.now(UTC)` и существование User; expired не возвращает User. Не пытаться удалять expired перед AuthError: такая запись откатится вместе с запросом.

  Перенести текущий AuthError и ContextVar в context/errors, переэкспортировать старые имена из auth/__init__.py: тесты домена не менять. PasswordHasher hash/verify выполнить через `asyncio.to_thread`, dummy hash создать один раз при инициализации passwords helper. get_me строит ShoppingListRead из доступных membership-списков, не импортирует shopping_list_service.

  AuthSettings: session_ttl_seconds и параметры лимитера из раздела решений, positive Field; `Settings.auth` имеет default_factory, поэтому старые конфигурации работают. Обновить `.env.example` и unit tests Settings. Сгенерировать миграцию `uv run alembic revision --autogenerate --rev-id 0003 -m 'create sessions'` на dev/test БД, просмотреть FK/indexes/downgrade.
- [x] **4. GREEN:** session/password/context/CLI tests; `scripts/test.sh tests/migrations`; `scripts/typecheck.sh`. Проверить отсутствие raw token и password в MeRead/model repr логов.
- [x] **5. Commit:** `git add backend/src/grocery backend/tests .env.example && git commit -m 'feat: add opaque database-backed cookie sessions'`.

## Task 3. Ограничение попыток входа

**Files:** Create `services/auth/rate_limit.py`. Modify `services/auth/sessions.py`, `services/auth/errors.py`, `schemas/auth.py`, `services/auth/__init__.py`. Test `tests/unit/test_login_rate_limit.py`, `tests/integration/test_login.py`.

**Produces:**

```python
class TooManyAttemptsError(Exception):
    retry_after: int

class LoginLimiter:
    def __init__(self, *, username_limit: int, ip_limit: int,
                 window_seconds: int, max_keys: int = 10000,
                 clock: Callable[[], float] = time.monotonic) -> None: ...
    def reserve(self, *, username: str, ip: str) -> None: ...

async def login(data: LoginCreate, *, device_id: str, ip: str) -> LoginResult: ...
```

Схемы сервиса (SessionIssued/MeRead — из Task 2):

```python
class LoginCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, AfterValidator(str.strip), Field(min_length=1, max_length=64)]
    password: str = Field(min_length=1, repr=False)

class LoginResult(BaseModel):
    session: SessionIssued
    me: MeRead
```

Поиск username case-sensitive, как create_user. LoginResult — внутренний сервисный результат, HTTP его не сериализует.

- [x] **1. Написать тесты sliding window:** отдельные IP/username ограничения; IP rotation не обходится за счёт общего username bucket, username rotation — общего IP bucket. Retry-After вычисляется по самой поздней из необходимых границ освобождения; reset только по времени. Инъекция monotonic clock, без sleep. При max_keys истёкшие удаляются, новые активные не вытесняют старые; отказ не увеличивает размер. Проверить допускаются ровно пять параллельных попыток одного username.

  ```python
  def test_username_limit_works_across_ips() -> None:
      limiter = LoginLimiter(username_limit=2, ip_limit=30, window_seconds=300, clock=lambda: 100.0)
      limiter.reserve(username="anna", ip="192.0.2.1")
      limiter.reserve(username="anna", ip="192.0.2.2")
      with pytest.raises(TooManyAttemptsError) as error:
          limiter.reserve(username="anna", ip="192.0.2.3")
      assert error.value.retry_after == 300
  ```

  Login integration: правильный пароль даёт новую сессию; неверный пароль и отсутствующий username оба AuthError с одинаковым `invalid_credentials`; сессия не создана. Лимит проверяется ДО Argon2 и выдаётся 429-предназначенное исключение даже при правильном пароле после превышения.

- [x] **2. RED:** `scripts/test.sh tests/unit/test_login_rate_limit.py tests/integration/test_login.py`.
- [x] **3. Реализовать limiter:** deque timestamps для prefixed ключей `("username", username)`/`("ip", ip)`, обработка окна и обоих лимитов синхронно в reserve без await. Проверка доступности/ёмкости всех нужных buckets до изменения; append в оба после успешной проверки. Один limiter на процесс через фабрику, читающую Settings; тесты создают изолированный limiter либо очищают кеш фабрики фикстурой. Login последовательно reserve → user_repo.by_username → verify_password → issue_session → построение MeRead для найденного user. Не делать commit; не ловить AuthError внутри UoW так, чтобы вернуть успех.
- [x] **4. GREEN:** targeted tests + `scripts/typecheck.sh`. Проверить счётчики переживают rollback запроса, потому что лимитер не в БД.
- [x] **5. Commit:** `git add backend/src/grocery/services/auth backend/src/grocery/schemas/auth.py backend/tests/unit/test_login_rate_limit.py backend/tests/integration/test_login.py && git commit -m 'feat: throttle login by username and IP'`.

## Task 4. HTTP-аутентификация, login/logout/me

**Files:** Modify `api/deps.py`, `api/errors.py`, `main.py`, `tests/api/conftest.py`. Create `api/routers/auth.py`, `api/routers/me.py`, `tests/api/test_auth.py`, `tests/api/test_auth_dependencies.py`.

**Produces:** `authenticate` async-yield dependency; `Authenticated = Depends(authenticate, scope="function")`; `DeviceIdDep` для login; `AppSourceDep = Annotated[AppSource, Depends(get_app_source)]` для protected мутаций; SessionCookie security; handlers AuthError 401/TooManyAttemptsError 429.

- [x] **1. Написать HTTP-тесты:**

  ```python
  async def test_login_cookie_and_me(client: httpx.AsyncClient, registered_user: None) -> None:
      response = await client.post("/api/auth/login", headers={"X-Device-Id": "phone"}, json={"username": "anna", "password": "test-password"})
      assert response.status_code == 200
      cookie = response.headers["set-cookie"]
      assert "__Host-gl_session=" in cookie
      assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
      assert "Path=/" in cookie and "Domain=" not in cookie
      assert response.json()["username"] == "anna"
      assert "password_hash" not in response.text
      assert (await client.get("/api/me")).status_code == 200
      assert (await client.post("/api/auth/logout", headers={"X-Device-Id": "phone"})).status_code == 204
      assert (await client.get("/api/me")).status_code == 401
  ```

  `registered_user` создать через create_user в UoW; API client base_url изменить на `https://testserver`, чтобы httpx отправлял Secure cookie. После каждого теста сбрасывать limiter, не отключать его для auth tests. Дополнительная матрица: invalid password/unknown username одинаковый ответ; expired/revoked/random cookie 401; cookie сменяется при повторном login; logout удаляет server session; X-Device-Id отсутствует/whitespace/>128 — 422; отсутствие cookie — 401; login source в body не принимается; context сброшен между запросами и после исключения; X-Forwarded-For не меняет limiter identity.

- [x] **2. RED:** `scripts/test.sh tests/api/test_auth.py tests/api/test_auth_dependencies.py`.
- [x] **3. Реализовать dependencies и роутеры:**

  ```python
  session_cookie = APIKeyCookie(name="__Host-gl_session", scheme_name="SessionCookie", auto_error=False)

  async def authenticate(
      token: Annotated[str | None, Security(session_cookie)],
      db: Annotated[None, DbUnitOfWork],
  ) -> AsyncIterator[None]:
      if token is None:
          raise AuthError("Требуется вход")
      with auth.acting_as(await auth.resolve_session(token)):
          yield
  ```

  Authenticated задаёт scope="function"; DbUnitOfWork остаётся существующим Depends instance, FastAPI кеширует его на запрос. Protected router dependencies=[Authenticated]; не добавлять второй независимый UoW в эндпоинт. Header-проверка выполняется после аутентификации protected роутера:

  ```python
  DeviceId = Annotated[str, AfterValidator(str.strip), Field(min_length=1, max_length=128)]

  async def get_device_id(
      device_id: Annotated[DeviceId, Header(alias="X-Device-Id")],
  ) -> str:
      return device_id

  DeviceIdDep = Annotated[str, Depends(get_device_id)]

  async def get_app_source(
      authenticated: Annotated[None, Authenticated],
      device_id: DeviceIdDep,
  ) -> AppSource:
      return AppSource(device_id=device_id)

  AppSourceDep = Annotated[AppSource, Depends(get_app_source)]
  ```

  Тесты закрепляют 401 до проверки X-Device-Id и схемы синтаксически корректного JSON. Некорректный JSON парсер FastAPI отклоняет до аутентификации с 422 `invalid_request`; эта граница также покрыта регрессионными тестами.

  Публичный login router: DbUnitOfWork и DeviceIdDep; вызов auth.login с request.client.host, user input и device_id. Login не использует AppSourceDep и не требует cookie. Login route возвращает result.me; response.set_cookie с параметрами из решений и max_age TTL. Logout защищён, получает исходный token через тот же Security dependency; auth.logout(token), response.delete_cookie с теми же атрибутами, 204. Me route только `return await auth.get_me()`.

  При 401 JSON ErrorResponse; password/unknown username тексты одинаковы. 429 добавляет Retry-After. Не возвращать WWW-Authenticate: Bearer для cookie-аутентификации. AuthError может иметь фиксированный code/message в отдельных подклассах CredentialsError/SessionError; generic AuthError default code not_authenticated сохраняет существующие импорты.
- [x] **4. GREEN:** auth HTTP tests, existing `test_unit_of_work_dependency.py`, health tests, mypy/import-linter. UoW exit/commit должны выполняться до отправки Set-Cookie и body; в тесте forced commit failure клиент не получает успешный login.
- [x] **5. Commit:** `git add backend/src/grocery/api backend/src/grocery/main.py backend/tests/api && git commit -m 'feat: expose cookie login logout and current user API'`.

## Task 5. REST позиций и тегов

**Files:** Create `api/routers/items.py`, `api/routers/tags.py`, `tests/api/test_items.py`, `tests/api/test_tags.py`, `tests/integration/test_delete_item.py`. Modify `schemas/items.py`, `schemas/tags.py`, `services/shopping_list_service/__init__.py`, `main.py`.

**Produces:** все item/tag routes таблицы контракта; `delete_item(id: UUID, source: Source) -> None` в сервисе; SetBought/ClearBought/TagBulk.

- [x] **1. Написать failing сценарии:** real HTTP batch add → quick-add merge → PATCH с явным quantity=null/note=null/tags=[] → bought → unbought → clear-bought. Проверить числовые quantities, сохранение оригинального имени, source.device_id из header в Event.source, отсутствие device/client ids в ItemRead.sources, count/204. Tag rename в существующий, простое rename, bulk bought/delete, delete tag без удаления items.

  ```python
  async def test_invalid_batch_is_atomic(client: httpx.AsyncClient, login_and_list: UUID) -> None:
      response = await client.post("/api/items", headers={"X-Device-Id": "phone"}, json={"shopping_list_id": str(login_and_list), "items": [{"name": "Лук"}, {"name": "Молоко", "quantity": -1}]})
      assert response.status_code == 422
      assert response.json()["details"][0]["loc"] == ["body", "items", 1, "quantity"]
      current = await client.get("/api/items", params={"shopping_list_id": str(login_and_list)})
      assert current.json() == []
  ```

  `login_and_list` — fixture: создать пользователя, login через HTTP, взять id из MeRead.shopping_lists. Матрица каждого маршрута: no-cookie 401; mutation без header 422; чужой id/list 404; некорректный UUID/body/unknown field 422. Проверить неверный ids в bought не меняет ни одной позиции/не пишет событие. Missing shopping_list_id не подменяется default, пустой AddItems/SetBought отклоняется. Не копировать все business-rule тесты домена: адаптер проверяет форму/аутентификацию/источник/делегирование.

  ```python
  async def test_delete_by_id_records_one_event(shopping_list_id: UUID) -> None:
      async with unit_of_work() as db:
          added = await service.add_items(AddItems(shopping_list_id=shopping_list_id, items=[ItemCreate(name="Лук")]), PHONE)
          await service.delete_item(added[0].item.id, PHONE)
          assert await service.get_items(shopping_list_id) == []
          assert await db.scalar(select(func.count()).select_from(Event).where(Event.type == EventType.ITEMS_DELETED)) == 1
  ```

  Интеграционный тест использует существующие service fixtures (перенести общие owner/list fixture в `tests/integration/conftest.py` при необходимости, не импортировать другой тестовый модуль).

- [x] **2. RED:** `scripts/test.sh tests/api/test_items.py tests/api/test_tags.py tests/integration/test_delete_item.py`.
- [x] **3. Реализовать новые схемы:**

  ```python
  class SetBought(BaseModel):
      model_config = ConfigDict(extra="forbid")
      shopping_list_id: UUID
      ids: list[UUID] = Field(min_length=1)
      bought: bool

  class ClearBought(BaseModel):
      model_config = ConfigDict(extra="forbid")
      shopping_list_id: UUID

  class TagBulk(BaseModel):
      model_config = ConfigDict(extra="forbid")
      action: Literal["mark_bought", "delete_items"]
  ```

  `delete_item` вызывает `_item_for_update(id)` и `_delete_items(item.shopping_list_id, [item], source)`; проверки доступа/lock/одно событие уже в сервисе. Роутер DELETE вызывает только delete_item, не загружает Item и не разрешает id через репозиторий. TagUpdate вход только, TagRead выход; computed_field name_normalized не возвращать пользователю как часть PATCH input.

  ```python
  router = APIRouter(prefix="/items", dependencies=[Authenticated], responses=PROTECTED_RESPONSES)

  @router.post("", response_model=list[AddItemResult])
  async def add(data: AddItems, source: AppSourceDep) -> list[AddItemResult]:
      return await service.add_items(data, source)

  @router.post("/clear-bought", response_model=CountRead)
  async def clear(data: ClearBought, source: AppSourceDep) -> CountRead:
      return CountRead(count=await service.clear_bought(data.shopping_list_id, source))
  ```

  PROTECTED_RESPONSES — mapping из Task 1/4 с ErrorResponse для 401/404/409/422/500. Login отдельно объявляет 429. У 204 явно response_class=Response, response_model=None, возвращать Response(status_code=204). Не полагаться на автоматическую сериализацию None. Валидация route inputs до вызова сервиса; весь batch сначала проходит Pydantic. query/path identifiers явно аннотированы UUID; include_bought default False.
- [x] **4. GREEN:** targeted + весь API/service набор, mypy/import-linter. OpenAPI response models в signatures не содержат ORM.
- [x] **5. Commit:** `git add backend/src/grocery backend/tests/api backend/tests/integration/test_delete_item.py backend/tests/integration/conftest.py && git commit -m 'feat: expose shopping items and tags REST API'`.

## Task 6. SSE без долгоживущей сессии БД

**Files:** Create `api/routers/events.py`, `tests/api/test_events.py`, `tests/support_sse.py`. Modify `api/deps.py`, `schemas/events.py`, `main.py`.

**Consumes:** auth.resolve_session/acting_as, ensure_shopping_list_access, event_hub.subscribe, EventRead, EventType.
**Produces:** `authorize_events(...) -> UUID`; `subscribe_events(...) -> AsyncIterator[Queue[EventRead]]` с request lifetime; `SseQueueDep`; `ShoppingListEvent` discriminated union, `ShoppingListEventRead(RootModel[ShoppingListEvent])`; GET /api/events.

- [x] **1. Написать тесты авторизации ДО stream:** no/expired/revoked cookie 401 JSON; чужой список 404 JSON; нет shopping_list_id 422; все ответы завершаются без ожидания heartbeat. Happy path через низкоуровневый ASGI harness: дождаться `http.response.start`, затем POST add-items отдельным запросом, получить `data:`; payload type/items/results/id совпадает с сохранённым event. Прервать receive сообщением http.disconnect, дождаться завершения task и проверить освобождение подписки. Session factory counter в harness подтверждает, что при ожидании queue у потока нет открытой сессии БД. Другой список не доставляется; rollback не доставляется.

  ```python
  async def test_sse_gets_committed_event(sse_client: SseClient, client: httpx.AsyncClient, login_and_list: UUID) -> None:
      async with sse_client.connect("/api/events", shopping_list_id=login_and_list, cookies=client.cookies) as stream:
          await stream.started()
          added = await client.post("/api/items", headers={"X-Device-Id": "phone"}, json={"shopping_list_id": str(login_and_list), "items": [{"name": "Лук"}]})
          frame = await stream.next_data(timeout=2)
          assert added.status_code == 200
          assert frame["type"] == "items_added"
          assert frame["payload"]["results"][0]["item"]["name"] == "Лук"
  ```

  SseClient — тестовый ASGI helper `tests/support_sse.py`, не production. connect запускает app(scope, receive, send) в task, `started()` ждёт capture response.start, next_data парсит JSON из завершённого SSE-frame, __aexit__ отправляет disconnect, отменяет и await task с timeout. Обычный httpx ASGITransport буферизует бесконечный ответ — для happy path его не использовать. Все waits ограничены timeout; не зависать на тестах.

- [x] **2. RED:** `scripts/test.sh tests/api/test_events.py`.
- [x] **3. Реализовать dependency и типы:**

  ```python
  async def authorize_events(
      shopping_list_id: UUID,
      token: Annotated[str | None, Security(session_cookie)],
  ) -> UUID:
      if token is None:
          raise AuthError("Требуется вход")
      async with unit_of_work():
          with auth.acting_as(await auth.resolve_session(token)):
              await service.ensure_shopping_list_access(shopping_list_id)
      return shopping_list_id
  ```

  SSE router НЕ имеет DbUnitOfWork/Authenticated на router-level: authorize_events сама открывает короткий UoW и закрывает до streaming. Request-scoped subscribe_events держит только очередь, не DB; subscribe происходит при разрешении dependencies до response.start, чтобы между началом ответа и регистрацией подписки не было зазора. Проверку cookie/list не помещать внутрь async generator endpoint — ошибки оттуда могут возникнуть после response.start. В потоке нет get_current_user()/get_current_session()/ORM.

  В schemas/events.py создать девять EventRead subclasses, type: Literal[EventType.X] с соответствующим default: ItemsAddedEvent, ItemUpdatedEvent, ItemsBoughtEvent, ItemsUnboughtEvent, ItemsDeletedEvent, BoughtClearedEvent, TagRenamedEvent, TagsMergedEvent, TagDeletedEvent. Их Annotated union discriminated по type назвать ShoppingListEvent, обернуть RootModel `ShoppingListEventRead` для именованного компонента генератора. Persisted EventRead/EventPayload не менять; корневая схема сериализуется тем же JSON-объектом, без дополнительного поля root.

  ```python
  async def subscribe_events(
      shopping_list_id: Annotated[UUID, Depends(authorize_events)],
  ) -> AsyncIterator[Queue[EventRead]]:
      with event_hub.subscribe(shopping_list_id) as queue:
          yield queue

  SseQueueDep = Annotated[Queue[EventRead], Depends(subscribe_events, scope="request")]

  @router.get("/events", response_class=EventSourceResponse, responses=SSE_PROTECTED_RESPONSES)
  async def events(queue: SseQueueDep) -> AsyncIterable[ShoppingListEventRead]:
      while True:
          snapshot = await queue.get()
          yield ShoppingListEventRead.model_validate(snapshot.model_dump())
  ```

  Yield typed data, а не ServerSentEvent с Any payload: FastAPI валидирует data по annotation и добавляет схемы в OpenAPI. Heartbeat/headers встроены. Cancellation завершает request-scoped dependency и освобождает subscribe context; обычные авторизованные роутеры по-прежнему используют function scope для UoW. Не добавлять собственные heartbeat tasks, replay БД или бессрочный DB generator.
- [x] **4. GREEN:** events API/hub/events integration tests; OpenAPI содержит text/event-stream и ShoppingListEventRead с discriminator/вариантами; stream не удерживает DB. Один smoke тест heartbeat может дождаться реальных 15 секунд с timeout 20, либо heartbeat проверить вручную через curl — не monkeypatch private FastAPI constants.
- [x] **5. Commit:** `git add backend/src/grocery/api backend/src/grocery/schemas/events.py backend/src/grocery/main.py backend/tests/api/test_events.py backend/tests/support_sse.py && git commit -m 'feat: stream authorized shopping events over SSE'`.

## Task 7. Экспорт OpenAPI, TypeScript и CI

**Files:** Modify `__main__.py`, `scripts/check.sh`, `scripts/typecheck.sh`, `Makefile`, `.github/workflows/ci.yml`, `README.md`. Create `scripts/api.sh`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`, `frontend/tests/api-contract.ts`, `backend/tests/unit/test_openapi.py`.

**Produces:** `python -m grocery export-openapi [--output PATH]`; `scripts/api.sh` для генерации, `scripts/api.sh --check` для немутирующей проверки; контракт обоих артефактов под версионным контролем.

- [x] **1. Написать contract tests:** есть все пути HTTP таблицы с явными response/schema/security; нет schemas с -Input/-Output, стандартного HTTPValidationError и raw session token в responses; SSE union компонент есть; ItemRead.quantity JSON schema number|null. CLI export работает без getpass, доступа к БД и lifespan; stdout — только JSON, повторные экспорты побайтово одинаковы. Invalid output path — ненулевой exit, без молчаливого успеха.

  ```python
  def test_read_quantity_schema_is_numeric() -> None:
      schema = create_app().openapi()
      quantity = schema["components"]["schemas"]["ItemRead"]["properties"]["quantity"]
      assert {part["type"] for part in quantity["anyOf"]} == {"number", "null"}

  def test_no_direction_suffixes() -> None:
      schemas = create_app().openapi()["components"]["schemas"]
      assert not any(name.endswith(("-Input", "-Output")) for name in schemas)
  ```

  Проверить cookie security login/health пустая, остальные protected включая events имеют SessionCookie. OpenAPI X-Device-Id required на всех мутациях. AuthError/DomainError schemas объявлены через responses, автоматический 422 переопределён.

- [x] **2. RED:** `scripts/test.sh unit -k openapi`; запуск пока отсутствующей export-openapi команды.
- [x] **3. Реализовать экспорт и генерацию:** `__main__.main` dispatch по subcommand ДО getpass/configure_engine. `export_openapi() -> str` создаёт app, получает app.openapi(), задаёт schema["info"]["version"]=importlib.metadata.version("grocery"), JSON indent=2/sort_keys=True/ensure_ascii=False + newline. Не добавлять runtime timestamps/host-dependent servers. Settings можно загрузить для create_app. Экспортному subprocess в scripts/api.sh задать `APP_PUBLIC_URL=http://localhost` и `DB_URL=postgresql+asyncpg://unused:unused@127.0.0.1:1/unused`: это фиксированные значения только для генерации, соединение не открывается; серверные секреты не нужны. CLI-тесты используют эти же значения через monkeypatch окружения. Чужой DB_URL не должен запускать configure_engine.

  ```json
  {
    "name": "grocery-frontend",
    "private": true,
    "type": "module",
    "scripts": {
      "api": "openapi-typescript src/api/openapi.json -o src/api/schema.d.ts",
      "typecheck": "tsc --noEmit"
    },
    "devDependencies": {
      "openapi-typescript": "7.13.0",
      "typescript": "5.9.3"
    }
  }
  ```

  `npm install --prefix frontend` создаёт lockfile, дальнейшие установки `npm ci --prefix frontend`. tsconfig strict/noEmit/skipLibCheck=false, target ES2022, module/moduleResolution NodeNext, include src/api/schema.d.ts и tests/api-contract.ts. Node 22 в CI через actions/setup-node (версию action проверить при исполнении), npm cache dependency frontend/package-lock.json, `npm ci`. Скрипты никогда не скачивают генератор через плавающий npx.

  `scripts/api.sh`: set -euo pipefail, определяет root независимо от cwd; default экспортирует JSON и запускает локальный frontend/node_modules/.bin/openapi-typescript. `--check`: создать mktemp directory с trap cleanup, экспортировать туда OpenAPI и TS тем же CLI, сравнить cmp с ОБОИМИ сохранёнными файлами, при отличии exit 1 и сообщение «Выполните scripts/api.sh и сохраните контракт». Отсутствующий файл тоже ошибка. Проверка не делает git diff всего репозитория и не перезаписывает артефакты. Проверить скрипт на изменённом API и отдельно изменённом schema.d.ts в disposable temp checkout; сравнить контрольные суммы файлов до/после --check.

  Add `scripts/api.sh --check` в scripts/check.sh; typecheck.sh после mypy вызывает `npm --prefix frontend run typecheck`. Makefile `api` вызывает scripts/api.sh. Обновить README: Node/npm ci, make api, команда export, Secure cookies и HTTPS base для ручных запросов. При появлении компонентов React инструменты будут расширены этапом 7.

  TypeScript fixture использует только generated components/paths; ошибки выявляет компилятор:

  ```typescript
  import type { components } from "../src/api/schema.js";
  declare const item: components["schemas"]["ItemRead"];
  const quantity: number | null = item.quantity;
  // @ts-expect-error quantity сериализуется числом, не строкой
  const wrongQuantity: string = item.quantity;
  declare const event: components["schemas"]["ShoppingListEventRead"];
  if (event.type === "items_added") {
    const results = event.payload.results;
    void results;
  }
  void quantity;
  void wrongQuantity;
  ```

  Проверить реально сгенерированные union/discriminator types; не заменять их ручными interfaces. OpenAPI SSE itemSchema может не попасть в тип ответа paths у генератора, но именованный ShoppingListEventRead обязан присутствовать в components и успешно сужаться по type.
- [x] **4. GREEN:** `scripts/api.sh`, `scripts/api.sh --check`, unit OpenAPI tests, `scripts/typecheck.sh`, shellcheck; проверить генерация не требует Docker. Свежий `scripts/check.sh` на полном дереве и `git diff --check`.
- [x] **5. Commit:** `git add backend/src/grocery/__main__.py backend/tests/unit/test_openapi.py scripts frontend Makefile .github/workflows/ci.yml README.md && git commit -m 'feat: generate and verify typed frontend API contract'`.

## Приёмка этапа и передача дальше

- [x] `scripts/fmt.sh`, `scripts/api.sh` и свежий `scripts/check.sh` выполнены; все исходные domain/API/CLI tests, новые session/API/SSE tests и миграции зелёные, API check не изменяет файлы.
- [x] Независимое итоговое ревью выполнено: cookie flags/hash/expiry, rate-limit concurrency, dependency scopes, 401/422 ordering, SSE authorization before headers, контракты schemas. Critical/Important отсутствуют; единственное Minor — формулировка порядка аутентификации/парсинга в плане — исправлено документацией.
- [x] Контракт для Swagger проверен OpenAPI-тестами: login/public security, cookie security protected routes, X-Device-Id, общий ErrorResponse. Проверка интерфейса Swagger UI не заявляется. HTTP-запросы проверены на реальном HTTPS-сокете; raw токен/пароль не сохранялись в коммитах/логах/скриншотах.
- [x] HTTPS SSE smoke выполнен HTTPX streaming по реальному TLS-сокету (эквивалент `curl -N`): login/cookie jar, отдельный POST quick-add, committed event, реальный heartbeat через 15 секунд, logout и 401 при новом соединении с отозванной cookie. Освобождение подписки при disconnect подтверждено API-тестами.
- [x] Статус этапа 3 в `docs/superpowers/plans/README.md` обновлён после свежего зелёного scripts/check.sh; число тестов и итог ревью записаны ниже.
- [ ] Следующий план — MCP/PAT; он переиспользует auth context, токен-хеш helper и те же сервисы списка. Деплой проверит прокси/SSE отдельно, не заявлять эту проверку выполненной локальными тестами.

## Self-review плана

| Требование | Задачи |
|---|---|
| Cookie сессии, hash, TTL, logout, Argon2 | 2, 4 |
| IP и username rate limit, Retry-After | 3, 4 |
| Текущий User в том же UoW, context reset | 2, 4 |
| X-Device-Id и достоверный source | 4, 5 |
| Все item/tag endpoints, атомарность, изоляция | 5 |
| SSE auth до ответа, поток без DB, teardown | 6 |
| JSON number, input/output схемы | 1, 7 |
| Единые ошибки, отсутствие секретов, 500 при failed commit | 1, 4, 5 |
| OpenAPI/TypeScript генерация и проверка в CI | 7 |
| Миграции upgrade/downgrade и реальные коммиты | 2, 4, 6 |

Политики TTL/лимитов явно заданы выше; внешних блокеров для реализации этого этапа нет. Чужие списки, no-cookie и malformed request покрываются матрицей; future-stage endpoints намеренно исключены.

## Проверенные первоисточники

- [FastAPI SSE tutorial](https://fastapi.tiangolo.com/tutorial/server-sent-events/): typed yield, heartbeat и response headers.
- [FastAPI yield dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/): function/request scopes и порядок закрытия ресурсов.
- [openapi-typescript CLI](https://openapi-ts.dev/cli): локальная генерация типов из файла.
- [openapi-typescript changelog](https://github.com/openapi-ts/openapi-typescript/blob/main/packages/openapi-typescript/CHANGELOG.md): версия 7.13.0.

Дополнительно сверены установленные FastAPI routing.py/sse.py и текущие API/service fixtures; отдельный frontend-каркас не предполагается существующим.

## Завершение — 2026-09-30

Этап 3 выполнен на ветке `feat/rest-api-sessions`; диапазон реализации `2eb97a3..61ed3af`.
Все семь задач прошли отдельные проверки соответствия плану и качества кода и получили
одобрение. Независимое итоговое ревью всего диапазона: **Ready to merge — Yes**,
Critical/Important отсутствуют. Единственное Minor о безусловном приоритете 401 исправлено:
аутентификация предшествует проверке заголовка и схемы корректного JSON, а malformed JSON
отклоняется транспортным парсером с 422. Иллюстрация SSE использует реализованную
`SSE_PROTECTED_RESPONSES` с JSON-ошибками.

Контроллер на `61ed3af` заново выполнил `env -u VIRTUAL_ENV scripts/check.sh`:
**394 теста прошли за 18.26 с**; Ruff проверил 97 файлов, mypy — 94 файла,
строгий TypeScript прошёл, все четыре import-linter контракта соблюдены.
Реальные PostgreSQL-тесты и migration stairway/model checks зелёные. OpenAPI/TS freshness
не изменяет артефакты; отдельный временный checkout подтвердил ошибки при дрейфе API,
каждого артефакта и отсутствии каждого файла с неизменными контрольными суммами.

Контроллер выполнил smoke на реальном Uvicorn с TLS и свежем PostgreSQL 18 после миграций:
secure-cookie login, me/list, quick-add с числовым quantity, committed SSE event,
реальный 15-секундный heartbeat, bought/clear, logout и новое SSE-соединение
с отозванной cookie → 401. Использован HTTPX streaming по TLS-сокету, эквивалентный
`curl -N`; ресурсы очищены. Swagger security/параметры/ошибки подтверждены OpenAPI-тестами,
визуальная проверка Swagger UI не заявляется. Проверка развёрнутого proxy/Cloudflare/SSE
и trusted-proxy настроек остаётся работой этапа 5.

### Принятые решения при реализации

| Решение | Причина | Цена пересмотра / следствие |
|---|---|---|
| Task 5: `TagUpdate` использует `extra=forbid`, отклоняя неизвестные/поддельные поля HTTP input. | Сохраняет достоверность Source и выполняет матрицу некорректного тела запроса. | Клиенты с лишними полями должны удалить их. |
| Общий probe-route helper перенесён в `tests/support_api.py`; существующий тест импортирует его. | Устраняет импорты между тестами и дублирование probe-роутов; production их не содержит. | При пересмотре потребуется отменить небольшой перенос test helper. |
| Неизвестный generic DomainError возвращает безопасный `internal_error` 500 без диагностических деталей. | Соответствует контракту неожиданных ошибок и не раскрывает новые ошибки без mapping. | Новому подтипу нужен явный mapping, чтобы вернуть доменный HTTP-ответ. |
| Dummy password hash инициализируется лениво и асинхронно; helper предоставляет `initialize_passwords()`, Task 4 прогревает его в lifespan. | Argon2 не блокирует event loop; первый неизвестный пользователь не платит за холодное создание хеша. | Startup выполняет одно дополнительное Argon2-хеширование; при пересмотре меняется инициализация helper. |
| Сохранён FastAPI malformed-JSON 422 до auth; 401 предшествует header/valid-JSON schema validation, Task 5 добавляет malformed-body regression. | Спецификация требует cookie-защиту и dependency auth; собственный pre-auth transport routing дублировал бы транзакционную инфраструктуру. | Неавторизованный malformed request получает 422 вместо 401; изменение потребует переработки слоя маршрутизации. Итоговое ревью приняло эту границу. |
| SSE ошибки описаны как `application/json`; отдельная карта централизованно производна от общих protected responses без model-driven event-stream inference. | Native EventSourceResponse иначе ошибочно описывает ошибки до начала потока как streams. | Небольшой mapping adapter может потребовать пересмотра при обновлении FastAPI. |
