# ADR-0008. Бизнес-логика списка — только в `shopping_list_service`; REST и MCP — адаптеры

Статус: принято · Дата: 2026-09-29

## Контекст

Позиции меняются двумя путями: пользователь в PWA (REST) и ассистент (MCP). Правила объединения,
нормализации, тегов, «куплено», запись событий и outbox (спец. §5, §7) обязаны работать
одинаково для обоих. Если хоть одно правило окажется в REST-обработчике, ассистент его обойдёт.

## Решение

- `services/shopping_list_service` — единственное место бизнес-логики списка. Это **модуль функций**, а не
  класс: пользователь и сессия берутся из контекста (ADR-0003, ADR-0004), репозитории — готовые
  объекты (ADR-0005), хранить в экземпляре нечего.
- Функция принимает схему операции и, если она мутирующая, источник:

  ```python
  async def add_items(data: AddItems, source: Source) -> list[AddItemResult]:
      await ensure_shopping_list_access(data.shopping_list_id)
      results = []
      for item in data.items:
          match = await item_repo.find_open_by_name(data.shopping_list_id, item.name_normalized, item.unit)
          if match:
              await item_repo.update(match, merge_item(match, item, source))   # §5.3
              status = AddStatus.MERGED
          else:
              match = await item_repo.add(item, shopping_list_id=data.shopping_list_id, sources=[source])
              status = AddStatus.CREATED
          await tag_repo.attach(match, item.tags)
          results.append(AddItemResult(status=status, item=ItemRead.model_validate(match)))
      await record_event(data.shopping_list_id, EventType.ITEMS_ADDED, source, results)
      return results
  ```

- **Каждая мутирующая функция пишет ровно одно событие** со своим `source` (спец. §7, п. 1)
  — через `events`, в той же транзакции. Пакетная операция — тоже одно событие.
- **Каждая функция начинается с проверки доступа** к списку (ADR-0003).
- Адаптер делает только одно — вызывает сервис с данными и источником:

  ```python
  # REST
  @router.post("/items")
  async def add_items(data: AddItems, source: AppSourceDep) -> list[AddItemResult]:
      return await shopping_list_service.add_items(data, source)

  # MCP
  @mcp_tool
  async def add_items(data: AddItems) -> list[AddItemResult]:
      return await shopping_list_service.add_items(data, get_mcp_source())
  ```

  Никаких условий по данным, обращений к репозиториям, записи событий. Если адаптеру нужна
  новая логика — это новая функция сервиса.
- Разница между дверями допустима только в форме: REST отдаёт схему как JSON, MCP — как
  результат инструмента с текстом для модели.
- Аутентификация, токены, OAuth — отдельный сервисный слой в `auth` (ADR-0010) по тем же правилам.

## Последствия

- Тесты бизнес-правил пишутся один раз — на сервис (ADR-0011); тесты адаптеров проверяют только
  маршрутизацию, аутентификацию и форму ответа.
- MCP-инструмент и REST-эндпоинт с одинаковым смыслом вызывают одну и ту же функцию — это видно
  при чтении и проверяется поиском по коду.

## Как проверяется

- `import-linter`: `api` и `mcp_server` не импортируют `db.repositories`, `db.models` и запись
  событий из `events`; разрешены только `db.session.unit_of_work` и подписка на SSE-хаб (ADR-0001).
- Тест: каждая мутирующая функция сервиса создаёт ровно одну строку в `events` с переданным `source`.
- Тест изоляции: каждая функция с `shopping_list_id` или `id` чужого списка → `NotFoundError`.
- Ревью: в адаптере нет `if` по данным позиции.
