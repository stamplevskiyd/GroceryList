# ADR-0017. Общий PATCH и обязательные payload событий

Статус: принято · Дата: 2026-10-03

## Контекст

Review этапа MCP/PAT выявил повтор полей ItemUpdate в MCP и отсутствие обязательных
полей payload у типизированных событий. Это ослабляло контракт ADR-0002/0009.

## Решение

- Плоский MCP update_item сохраняется. UpdateItemArguments наследует ItemUpdate и
  SDK ArgModelBase; общая схема задаёт все поля, ограничения и валидаторы.
  Единственное преобразование model_dump_one_level собирает ItemUpdate через
  exclude_unset, сохраняя разницу между пропуском и null. Ручного списка PATCH-полей нет.
- Name и Unit определены в schemas/common.py. Name ограничивает отображаемое имя
  и нормализованный ключ; Unit проверяет длину нормализованной единицы. Ключи не обрезаются.
  TagRead располагается в schemas/tags.py.
- Payload определяется видом события: items_added требует results; операции позиций
  требуют items; tag_renamed/tags_merged требуют tag и previous_tag; tag_deleted — tag.
  EventCreate/EventRead проверяют соответствие type и payload, варианты SSE объявляют
  конкретный тип payload. Пустые массивы допустимы для операций без изменённых позиций.
- Миграция 0005 удаляет из существующих JSONB только неиспользуемые поля старого общего
  payload. Downgrade восстанавливает их прежние значения по умолчанию; используемые
  снимки позиций и тегов сохраняются. Перед чтением старых событий требуется upgrade head.
- Неожиданный ValidationError из тела MCP-инструмента — внутренний сбой с безопасным
  сообщением. Ошибки входного PATCH обрабатывает SDK при валидации UpdateItemArguments.

## Проверки

- Сравнение каждого PATCH-поля REST и плоской MCP JSON Schema; transport tests для
  пропуска, null, tags=[] и невалидных данных.
- Пустой payload отклоняется для всех девяти событий; TS после сужения tags_merged
  получает обязательные TagRead для обоих тегов.
- Unicode lower expansion не выходит за пределы PostgreSQL VARCHAR; граничные значения
  успешно записываются в реальный Postgres.
- Миграция на заполненных данных всех девяти типов: upgrade, downgrade, повторный upgrade
  сохраняют полезный payload; model check и stairway остаются зелёными.
