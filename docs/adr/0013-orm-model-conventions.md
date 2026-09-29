# ADR-0013. Соглашения ORM-моделей и миграций

Статус: принято · Дата: 2026-09-29

## Контекст

Модели меняются миграциями Alembic (спец. §10), и часть решений на уровне моделей потом дорого
переделывать: нативные enum-типы Postgres, неявные имена ограничений, даты без часового пояса.
Эти правила должны быть одинаковыми для всех таблиц с первой миграции.

## Решение

### Статусы и другие перечисления — `StrEnum` без нативного типа Postgres

```python
class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"

status: Mapped[OutboxStatus] = mapped_column(
    SAEnum(
        OutboxStatus,
        native_enum=False,                                   # VARCHAR, а не CREATE TYPE
        length=32,                                           # запас под новые значения
        values_callable=lambda e: [m.value for m in e],      # храним value, а не имя
        validate_strings=True,
    )
)
```

- `native_enum=False`: нативный `ENUM` Postgres требует отдельных, неудобных в Alembic миграций
  на каждое добавление значения (автогенерация их не видит, `ALTER TYPE` нельзя в транзакции
  в старых версиях). VARCHAR снимает эту проблему.
- `length=32` задаётся явно: по умолчанию длина берётся по самому длинному значению, и новое
  более длинное значение потребовало бы миграции.
- `values_callable`: по умолчанию SQLAlchemy пишет в БД **имя** члена (`PENDING`), а не значение.
- CHECK-ограничение не создаём (`create_constraint=False` — по умолчанию): добавление значения
  не требует миграции, корректность обеспечивает приложение.
- Так оформляются: `OutboxStatus`, `MemberRole`, `EventType`, `AddStatus` и любые будущие
  перечисления. Тот же `StrEnum` используется в Pydantic-схемах.

### Общие поля и типы

- Первичный ключ — `id: Mapped[UUID]`, генерируется в приложении: `default=uuid7`
  (`uuid.uuid7`, Python 3.14). UUIDv7 упорядочен по времени — вставки идут в конец индекса,
  а не в случайное место, как с `uuid4`.
- `created_at`, `updated_at` — `DateTime(timezone=True)` (`timestamptz`),
  `server_default=func.now()`; `updated_at` обновляется `onupdate=func.now()`. Даты без часового
  пояса запрещены (ruff `DTZ`).
- Количество — `Numeric`, в Python `Decimal`; `float` для количеств не используется.
- `jsonb` — для `sources`, `events.source`, `events.payload`. Колонка объявляется своим типом
  `PydanticJSON(<схема>)` (`TypeDecorator` в `db/types.py`): атрибут модели — типизированные
  Pydantic-объекты (`item.sources: list[Source]`), сериализация и валидация — в одном месте.
- Изменения внутри `jsonb` на месте SQLAlchemy не отслеживает: `item.sources.append(...)` не
  сохранится. Значение всегда присваивается целиком: `item.sources = [*item.sources, source]`
  (так и работает `Repository.update`, ADR-0005).
- Стиль SQLAlchemy 2.0: `Mapped[...]`, `mapped_column`; связи — `lazy="raise"` (ADR-0005).

### Имена

- Модели — в единственном числе (`Item`, `ShoppingList`), таблицы — во множественном
  (`items`, `shopping_lists`). Таблицы связей — по двум сущностям: `item_tags`,
  `shopping_list_members`.

### Имена ограничений и миграции

- `MetaData(naming_convention=...)` в базовом классе моделей — стабильные имена индексов,
  уникальных и внешних ключей (`uq_items_shopping_list_id_name_normalized`), чтобы Alembic мог их
  удалять и переименовывать.
- Миграции — `alembic revision --autogenerate`, затем обязательный просмотр и правка руками.
  Имя файла — с датой: `2026_09_29_1200-<rev>_<slug>.py` (`file_template` в `alembic.ini`).
- Данные в миграциях меняются явным SQL / `op.execute`, без импорта ORM-моделей приложения.
- **Каждая миграция содержит рабочий `downgrade`**, полностью отменяющий `upgrade` (включая
  индексы, ограничения, данные, где это возможно). Если отмена невозможна без потери данных —
  `downgrade` явно бросает исключение с объяснением, а не остаётся пустым.

## Последствия

- Добавление значения в перечисление — правка `StrEnum`, без миграции.
- Цена: БД не защищает от неверного значения статуса, если писать в неё в обход приложения.

## Как проверяется

- Тест: у всех колонок типа `Enum` в `Base.metadata` — `native_enum=False` и явная длина.
- Тест: `alembic upgrade head` на пустой БД + `alembic check` (модели и миграции совпадают) —
  в наборе тестов (ADR-0011).
- Stairway-тест: для каждой ревизии `upgrade` → `downgrade` → `upgrade` (ADR-0011).
