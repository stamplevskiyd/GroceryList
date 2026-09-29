# ADR-0005. Доступ к данным — через репозитории со стандартным набором методов

Статус: принято · Дата: 2026-09-29

## Контекст

Нужен единый стандарт работы с моделями: одинаковые операции (`get`, `add`, `update`, `delete`)
не должны переписываться в каждом месте, а SQL не должен расползаться по сервисам и адаптерам.
Это известный паттерн обобщённого CRUD-репозитория (`CRUDBase` из шаблона full-stack-fastapi).

## Решение

### Базовый класс — стандарт для всех репозиториев

```python
class Repository[M: Base, C: BaseModel, U: BaseModel]:
    exclude_on_write: ClassVar[set[str]] = set()     # поля схемы, которые не пишутся в модель напрямую

    def __init__(self, model: type[M]) -> None:
        self.model = model

    async def get(self, id: UUID) -> M | None: ...
    async def get_by_ids(self, ids: Sequence[UUID]) -> list[M]: ...

    async def add(self, data: C, **extra: Any) -> M:
        obj = self.model(**data.model_dump(exclude=self.exclude_on_write), **extra)
        session = get_current_session()
        session.add(obj)
        await session.flush()
        return obj

    async def update(self, obj: M, data: U) -> M:
        values = _values(data, exclude=self.exclude_on_write, only_set=True)
        for field, value in values.items():
            setattr(obj, field, value)
        await get_current_session().flush()
        return obj

    async def delete(self, obj: M) -> None: ...
```

- `add` принимает Pydantic-схему создания; `**extra` — поля, которых нет во входной схеме и
  которые задаёт сервис (`shopping_list_id`, `sources`).
- `update` принимает схему с частичными полями и меняет только переданные. Вычисляемые поля
  (`computed_field`, например `name_normalized`) пишутся, если их значение не `None`: в схемах
  обновления вычисляемое поле возвращает `None`, когда исходное поле не передано.
- `add` / `add_all` пишут все поля схемы, включая вычисляемые; вложенные Pydantic-объекты
  передаются как объекты (их сериализует тип колонки, ADR-0013).
- Методы для коллекций: `get_by_ids`, `delete_by_ids`, `add_all`. Суффиксы `_list` и `_many` не
  используются — «list» в проекте занят списком покупок (`ShoppingList`).
- Сессия — из `get_current_session()` (ADR-0004); в конструктор не передаётся.

### Конкретные репозитории

- Наследуют базу и добавляют **только запросы, которых в ней нет**:

  ```python
  class ItemRepository(Repository[Item, ItemCreate, ItemUpdate]):
      exclude_on_write = {"tags"}          # связь, выставляется отдельно

      async def find_open_by_name(
          self, shopping_list_id: UUID, name_normalized: str, unit: str | None
      ) -> Item | None: ...

  item_repo = ItemRepository(Item)
  ```

- Репозитории без состояния, поэтому это готовые объекты модуля: `item_repo`, `tag_repo`, …
  (классметоды не используем: mypy strict не пропускает обращение к обобщённому `cls.model`).
- Методы-запросы с фильтрами принимают `shopping_list_id` явно. Проверка, что пользователь имеет доступ
  к списку, — в сервисе (ADR-0003), а не в репозитории.
- Результаты, не являющиеся моделью, — маленький `@dataclass(frozen=True, slots=True)` в модуле
  репозитория (`TagUsage(tag: Tag, open_count: int)`), не кортежи и не `Row`.

### Чего в репозитории нет

- **Бизнес-правил.** Объединение позиций (спец. §5.3) — чистая функция
  `merge_item(existing, incoming, source) -> ItemUpdate` в сервисном слое; применяет её
  стандартный `update`. Так правило тестируется без БД, а набор методов репозитория остаётся
  стандартным.
- **Транзакций.** Репозитории не коммитят и не откатывают; `flush()` допустим.

### Связи

- Ленивая загрузка в async запрещена: связи моделей объявлены с `lazy="raise"` (ADR-0013).
- Загрузка — явно, `selectinload` в методе репозитория. `ItemRepository` загружает теги всегда.

## Рассмотренные альтернативы

- **Репозиторий, привязанный к списку через конструктор** — изоляция «бесплатно», но после
  решения передавать `shopping_list_id` явно в данных (ADR-0003) привязка теряет смысл, а экземпляр на
  каждый запрос — лишний шум.
- **`SQLAlchemyAsyncRepository` из `advanced-alchemy`** — тянет свои базовые модели, объекты
  фильтров и передачу сессии через конструктор.

## Последствия

- Новый репозиторий — это обычно три строки: класс с параметрами типов и экземпляр.
- Сервисы тестируются на реальной БД (ADR-0011) без моков репозиториев.
- Запросы, которым тесно в репозитории, сервис выполняет через `get_current_session()` — это
  допустимо и не требует нового метода ради одного вызова.

## Как проверяется

- `import-linter`: `sqlalchemy` импортируется только в `db` и в сервисах (для запросов через
  `get_current_session()`), но не в адаптерах и схемах.
- Тесты базового `Repository`: `add` / `update` (включая `exclude_unset`) / `delete` / `get_by_ids`.
- Ревью: метод конкретного репозитория, дублирующий базовый, или содержащий правило из спец. §5.
