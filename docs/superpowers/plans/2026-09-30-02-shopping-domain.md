# Домен списка покупок — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Выполнить этап 2: проверяемый домен списка покупок, события и CLI создания пользователя.

**Architecture:** Схемы нормализуют вход, репозитории выполняют SQL, модуль `shopping_list_service` содержит бизнес-правила. Пользователь и сессия берутся из ContextVar. Мутации сериализуются блокировкой строки списка; события сохраняются в той же транзакции и публикуются через SQLAlchemy after_commit.

**Tech Stack:** Python 3.14, Pydantic 2, SQLAlchemy 2.1 async, Alembic, Postgres 18, pytest, argon2-cffi.

**Spec:** `docs/superpowers/specs/2026-09-29-grocery-list-design.md`, §3–5, §7, §11; ADR-0001–0014.

## Global Constraints

- Количества — Decimal, не float; UUIDv7; даты с часовым поясом.
- Сервисы — модуль функций; commit/rollback только в unit_of_work.
- Внешние и внутренние данные — типизированные Pydantic-схемы; JSONB — PydanticJSON.
- Связи lazy="raise", теги загружаются явно.
- Каждая мутация пишет одно событие; чужие объекты возвращают NotFoundError.
- Пакеты атомарны; уникальность тегов в рамках списка.
- Outbox и push относятся к этапу 8; HTTP/SSE endpoint — к этапу 3.
- Готовность: `scripts/check.sh` проходит, включая миграции на реальном Postgres.

## 1. Нормализация и быстрый ввод

Files: `domain/normalization.py`, `domain/quick_add.py`, `schemas/items.py`, `schemas/sources.py`, `domain/enums.py`, `domain/errors.py`, `tests/unit/test_shopping_domain.py`.

Interfaces: `normalize_name(str) -> str`, `normalize_quantity(Decimal | None, str | None) -> tuple[Decimal | None, str | None]`, `parse_quick_add(str) -> ParsedItem`; `ItemCreate`, `ItemUpdate`, `ItemRead`, `AddItems`, `AddItemResult`.

- [x] Написать параметризованные примеры §5.6 и тесты пустого/неположительного ввода, частичного обновления, ё и пробелов.
  ```python
  assert normalize_name("  Зелёный  ЛУК ") == "зеленый лук"
  assert parse_quick_add("яблоки 1,5 кг").quantity == Decimal("1500")
  ```
- [x] Запустить `scripts/test.sh unit -k shopping_domain`, увидеть отсутствие модулей.
- [x] Реализовать чистые функции, discriminated Source и схемы; нормализовать единицы только при наличии соответствующего поля.
- [x] Повторить тесты до зелёного результата.

## 2. Хранение и миграция

Files: `db/types.py`, `db/models/shopping.py`, `db/models/event.py`, `db/models/__init__.py`, `db/repositories/shopping.py`, новая ревизия `0002`, `tests/integration/test_shopping_storage.py`.

Interfaces: `PydanticJSON[T]`, `ShoppingList`, `ShoppingListMember`, `Item`, `Tag`, `Event`; `shopping_list_repo`, `item_repo`, `tag_repo`, `event_repo`. `shopping_list_repo.lock(id)` блокирует строку FOR UPDATE; `item_repo.find_open_by_name` ищет только некупленные с той же базовой единицей.

- [x] Проверить хранение Source и Decimal после повторной загрузки, связи и поиск только открытых позиций.
  ```python
  assert stored.sources == [AppSource(device_id="phone")]
  assert stored.quantity == Decimal("1500")
  ```
- [x] Запустить `scripts/test.sh tests/integration/test_shopping_storage.py` и увидеть отсутствие моделей.
- [x] Добавить модели с FK CASCADE и индексами, типизированный JSONB, репозитории; сгенерировать миграцию Alembic и проверить upgrade/downgrade.
- [x] Запустить storage и migration tests; `alembic check` должен подтвердить соответствие моделей.

## 3. Пользователь и события

Files: `services/auth.py`, `services/events.py`, `services/event_hub.py`, `schemas/events.py`, `schemas/shopping_lists.py`, `tests/integration/test_shopping_events.py`.

Interfaces: `acting_as(User)`, `get_current_user() -> User`, `create_user(username, password) -> User`; `record_event(shopping_list_id, type, source, payload) -> EventRead`; `event_hub.subscribe(shopping_list_id)` — context manager очереди.

- [x] Тестировать создание пользователя + списка + owner membership и проверку argon2; доставку после настоящего коммита и отсутствие доставки при rollback.
  ```python
  assert queue.empty()  # внутри unit_of_work
  assert (await queue.get()).type == EventType.ITEMS_ADDED  # после выхода
  ```
- [x] Запустить targeted tests, увидеть отсутствие сервиса.
- [x] Добавить контекст с обязательным reset, создание списка атомарно и SQLAlchemy listeners на конкретной сессии. Очереди ограничены, при переполнении остаются последние события; переподключение reload предусмотрено спецификацией.
- [x] Запустить targeted tests, включая разделение событий по спискам.

## 4. Операции списка

Files: `services/shopping_list_service.py`, `services/item_merge.py`, `schemas/tags.py`, `tests/unit/test_item_merge.py`, `tests/integration/test_shopping_service.py`.

Interfaces: `add_items(AddItems, Source)`, `quick_add(QuickAdd, Source)`, `get_items(UUID, include_bought=False)`, `update_item(UUID, ItemUpdate, Source)`, `set_bought(UUID, ids, bought, Source)`, `remove_items(UUID, Source, ids=..., tag=...)`, `clear_bought(UUID, Source)`, `list_tags(UUID)`, `rename_tag(UUID, str, Source)`, `delete_tag(UUID, Source)`, `bulk_tag(UUID, action, Source)`, `get_default_shopping_list_id()`.

- [x] Написать тесты §5.3–5.7: суммирование/nullable, несовместимые единицы, bought, источники без device/client ids, заметки, теги и их объединение, сортировка, одно событие на пакет, история удалённых позиций и изоляция каждой операции.
  ```python
  assert results[0].status == AddStatus.MERGED
  assert results[0].item.quantity == Decimal("1500")
  ```
- [x] Запустить targeted tests, увидеть отсутствие операций.
- [x] Реализовать сервис с проверкой membership перед чтением/записью, lock списка перед каждой мутацией. Проверять все id перед изменением. PATCH сохраняет явно переданные null, unit меняется с пересчётом количества; PATCH не объединяет записи.
- [x] Запустить тесты; отдельно проверить гонку двух add_items на настоящих коммитах: одна открытая позиция, сумма обоих количеств.

## 5. CLI и завершение

Files: `grocery/__main__.py`, `tests/integration/test_create_user_cli.py`, `README.md`, `docs/superpowers/plans/README.md`.

Interfaces: `python -m grocery create-user USERNAME` запрашивает пароль через getpass, не принимает пароль аргументом командной строки.

- [x] Написать тест вызова CLI с тестовой фабрикой сессий; проверить хеш, owner membership, отказ при повторном имени без второго списка.
- [x] Запустить тест, увидеть отсутствие команды.
- [x] Реализовать argparse/getpass, lifecycle движка, понятный ненулевой код ошибки; документировать команду.
- [x] Выполнить `scripts/fmt.sh` и `scripts/check.sh`; отметить этап завершённым только после успешной проверки.

## Результат выполнения — 2026-09-30

- Все пять задач выполнены в ветке `feat/shopping-domain`, в исходной директории проекта.
- `scripts/check.sh`: ruff format/check, четыре контракта import-linter, shellcheck, mypy strict и **113 тестов — зелёные**.
- Миграция 0002 сгенерирована на временном Postgres, JSONB-типы исправлены вручную на независимые от приложения типы PostgreSQL. Stairway и alembic check проходят.
- Проверены параллельные добавления на настоящих коммитах, изоляция всех операций, публикация после commit и отсутствие публикации после rollback.
- Независимое ревью Superpowers обнаружило два дефекта: обработка нестроковых названий/тегов до проверки типов и повтор составной заметки. Оба воспроизведены регрессионными тестами и исправлены.
- CLI: `uv run python -m grocery create-user USERNAME`; пароль вводится скрыто дважды. `--help` проверен.
- Следующий план: этап 3 — cookie-сессии, REST API, SSE-эндпоинт, OpenAPI. План этапа 3 следует писать с учётом реализованных интерфейсов.
