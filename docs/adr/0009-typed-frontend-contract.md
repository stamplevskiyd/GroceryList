# ADR-0009. Типизированный контракт фронтенд ↔ бэкенд через OpenAPI

Статус: принято · Дата: 2026-09-29

## Контекст

Владелец — backend-разработчик; фронтенд пишется по макету и проверяется вручную (спец. §1).
Расхождение между тем, что отдаёт бэкенд, и тем, что ждёт фронтенд, должно ловиться компилятором
TypeScript, а не на телефоне. Swagger UI (`/docs`) показывает контракт человеку, но не мешает
фронтенду читать несуществующее поле.

## Решение

### Источник правды и генерация

- Источник правды — Pydantic-схемы бэкенда (ADR-0002). FastAPI строит из них OpenAPI;
  Swagger UI на `/docs` остаётся для ручной проверки.
- `scripts/api.sh` (ADR-0007):
  1. `uv run python -m grocery export-openapi` → `frontend/src/api/openapi.json`;
  2. `openapi-typescript` → `frontend/src/api/schema.d.ts`.
  Оба файла коммитятся: фронтенд собирается в Docker без запуска бэкенда, изменения контракта
  видны в диффе.
- Клиент — `openapi-fetch` (типизированная обёртка над `fetch`, без сгенерированного кода),
  запросы и кэш — TanStack Query через `openapi-react-query`:

  ```ts
  const { data } = $api.useQuery("get", "/api/items", { params: { query: { shopping_list_id } } });
  ```

  Ручные `fetch` к `/api` и объявленные вручную типы ответов запрещены.

### Правила для схем, влияющие на контракт

- **Одна схема — одно направление.** `*Create` / `*Update` — только вход, `*Read` — только
  выход. Иначе FastAPI разбивает схему на `X-Input` / `X-Output` (из-за значений по умолчанию
  и `computed_field`), и во фронтенд попадают неудобные имена.
- **Количество — число в JSON.** На бэкенде `Decimal` (точные суммы при объединении), в JSON —
  `number`: общий тип `Quantity = Annotated[Decimal, PlainSerializer(float, return_type=float,
  when_used="json")]`. Без этого Pydantic сериализует `Decimal` в строку.
- `UUID` и даты — строки (ISO 8601) в JSON; во фронтенде даты разбираются в одном месте.
- Ошибки — единая схема `{code, message}` (ADR-0012), объявленная в `responses` роутеров.

### Живые обновления — встроенный SSE FastAPI

```python
@router.get("/events", response_class=EventSourceResponse)
async def events(shopping_list_id: UUID) -> AsyncIterable[ShoppingListEvent]: ...

ShoppingListEvent = Annotated[ItemsAdded | ItemsBought | ..., Field(discriminator="type")]
```

- `fastapi.sse.EventSourceResponse` (FastAPI ≥ 0.135) валидирует события по аннотации и
  описывает их в OpenAPI; модели событий попадают в `components.schemas` и во фронтенд — тем же
  генератором.
- Keep-alive ping каждые 15 секунд, `Cache-Control: no-cache`, `X-Accel-Buffering: no` —
  FastAPI выставляет сам.
- Получив событие, фронтенд инвалидирует соответствующие запросы TanStack Query; при
  переподключении — перезапрашивает список целиком (спец. §7).

## Рассмотренные альтернативы

- **Типы вручную + Swagger как документация** — расхождения не ловятся компилятором.
- **`@hey-api/openapi-ts`** — генерирует полноценный SDK; версия 0.x с частыми ломающими изменениями.
- **`orval`** — хуки react-query и моки MSW; моки не нужны — бэкенд поднимается `docker compose up`.

## Последствия

- Изменение схемы на бэкенде → `scripts/api.sh` → `tsc` показывает все места во фронтенде,
  которые сломались.
- Фронтенд зависит от трёх небольших библиотек (`openapi-fetch`, `openapi-react-query`,
  `@tanstack/react-query`) и одного dev-инструмента (`openapi-typescript`).

## Как проверяется

- `scripts/check.sh` запускает `scripts/api.sh`; если `openapi.json` или `schema.d.ts`
  изменились — проверка падает («контракт изменён, но не перегенерирован»).
- `tsc --noEmit` во фронтенде — в `scripts/typecheck.sh`.
- Тест: в OpenAPI нет схем с суффиксами `-Input` / `-Output`.
