# ADR-0012. Доменные ошибки и их перевод в REST и MCP

Статус: принято · Дата: 2026-09-29

## Контекст

Одна и та же ошибка («позиция не найдена», «пустой список позиций») должна приходить одинаково
понятной и в PWA, и ассистенту (спец. §6.2: ошибки инструментов — MCP tool errors с понятным
текстом). Если каждый обработчик ловит исключения сам, тексты и коды разойдутся, а часть ошибок
превратится в 500. При этом человеку и модели нужны разные подсказки: пользователю PWA не нужно
имя MCP-инструмента, а модели оно помогает исправить вызов.

## Решение

### Иерархия — `domain/errors.py`

```python
class DomainError(Exception):
    code: ClassVar[str]              # стабильный машинный код: "item_not_found"
    message: ClassVar[str]           # текст для человека, по-русски
    hint: ClassVar[str | None] = None  # подсказка для модели — только в MCP

    def __init__(self, message: str | None = None, *, details: list[ErrorDetail] | None = None): ...

class NotFoundError(DomainError): ...        # 404
class InvalidInputError(DomainError): ...    # 422
class ConflictError(DomainError): ...        # 409 — зарезервировано, в v1 не используется

class ItemNotFoundError(NotFoundError):
    code = "item_not_found"
    message = "Позиция не найдена — возможно, её уже удалили"
    hint = "Вызови get_shopping_list, чтобы получить актуальные id"
```

- Конкретные ошибки — подклассы с фиксированными `code`, `message`, `hint`; при необходимости
  `message` уточняется в конструкторе.
- `InvalidInputError`, а не `ValidationError` — чтобы не путать с `pydantic.ValidationError`.
- `ErrorDetail = {loc: list[str | int], message: str}` — ошибки по полям.
- **Чужой список или объект чужого списка — `NotFoundError`** (`shopping_list_not_found`,
  `item_not_found`): ответ неотличим от несуществующего, 403 не используется (ADR-0003).
- Сервис бросает только `DomainError` (или неожиданные исключения — это баги). Репозиторий
  `DomainError` не бросает: «не нашлось» — это `None`, решение об ошибке — в сервисе.
- **Пакетные операции атомарны**: невалидная позиция в `add_items` отменяет весь пакет,
  `details` указывает её (`loc: ["items", 3, "quantity"]`).

### Перевод — в одном месте на адаптер

- **REST** — exception handler приложения, ответ `ErrorResponse = {code, message, details?}`
  (объявлен в `responses` роутеров, ADR-0009):
  - `NotFoundError` → 404, `InvalidInputError` → 422, `ConflictError` → 409;
  - ошибки валидации запроса от FastAPI → 422 в той же схеме, `code="invalid_request"`,
    `details` из ошибок Pydantic;
  - `hint` в REST не отдаётся.
- **MCP** — middleware `MCPServer` на `tools/call` (та же, что открывает `unit_of_work`,
  ADR-0004, ADR-0010) ловит `DomainError` и бросает `ToolError` с текстом
  `message` + `hint` (+ `details`, если есть) — модель видит, что пошло не так и что делать.
  Ошибки валидации аргументов SDK возвращает сам (текст Pydantic) — не оборачиваем.
- **Неожиданное исключение** — лог уровня `error` со стеком; клиенту — 500 / tool error
  «Внутренняя ошибка» без деталей.
- Обработчики и инструменты не содержат `try/except DomainError`.

### Ошибки аутентификации — не доменные

Живут в `auth`, не наследуют `DomainError`:

- `AuthError` → 401 (REST); в MCP 401 с `resource_metadata` формирует SDK (ADR-0010);
- `TooManyAttemptsError` (ограничение попыток входа) → 429 с `Retry-After`;
- OAuth-эндпоинты отвечают ошибками по RFC 6749 (`invalid_grant`, `invalid_request`, …),
  а не `ErrorResponse`.

### Язык и логирование

- Тексты `message` и `hint` — на русском, как и описания MCP-инструментов: названия позиций
  русские, пользователю модель отвечает на его языке.
- `DomainError` логируется на уровне `info` с `code` — это ожидаемая ситуация, не сбой.

## Последствия

- Новая ошибка — это новый подкласс; адаптеры менять не нужно.
- Тексты для человека и подсказки для модели лежат рядом и не мешают друг другу.

## Как проверяется

- Тесты адаптеров: одна и та же ошибка сервиса даёт ожидаемый статус, `code` и `message` в REST
  (без `hint`) и tool error с `message` + `hint` в MCP.
- Тест: все подклассы `DomainError` имеют уникальный `code`, непустой `message` и статус в маппинге.
- Тест: невалидная позиция в пакете — ни одна позиция не добавлена, `details.loc` указывает на неё.
