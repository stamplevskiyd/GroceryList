# ADR-0004. Одна сессия БД на единицу работы, хранится в `ContextVar`

Статус: принято · Дата: 2026-09-29

## Контекст

Нужна одна `AsyncSession` на запрос: все репозитории внутри запроса работают в одной транзакции,
а мутация, событие и строки outbox коммитятся вместе (спец. §7). Прокидывать сессию аргументом
через каждый сервис и репозиторий шумно. Распространённый паттерн — хранить сессию в
`ContextVar` (так делают `fastapi-async-sqlalchemy`, `context-async-sqlalchemy`).

Ограничения, которые учитываем:

- SQLAlchemy не рекомендует `async_scoped_session(scopefunc=current_task)`: он опирается на
  глобальное состояние, требует ручного `remove()`, а Starlette-middleware выполняет запрос
  в другой задаче. Поэтому ключ — `ContextVar`, а не текущая задача.
- Сессию открывают три разных вызывающих: REST-запрос, вызов MCP-инструмента, итерация
  push-воркера. MCP SDK может выполнять инструменты не в задаче HTTP-запроса, поэтому
  middleware, выставленное на HTTP-уровне, до инструмента может не дойти.
- В FastAPI код выхода dependency с `yield` по умолчанию (`scope="request"`) выполняется
  **после** отправки ответа — коммит после ответа означал бы «200 OK» при упавшем коммите.
- SSE-поток живёт минутами и не должен держать сессию.

## Решение

Один модуль `db/session.py` — единственное место, где создаются сессии:

```python
_session: ContextVar[AsyncSession | None] = ContextVar("db_session", default=None)

@asynccontextmanager
async def unit_of_work() -> AsyncIterator[AsyncSession]:
    """Открыть сессию, выставить её в контекст, закоммитить при успехе."""
    if _session.get() is not None:
        raise RuntimeError("unit_of_work уже открыт в этом контексте")
    async with session_factory() as session:
        token = _session.set(session)
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            _session.reset(token)

def get_current_session() -> AsyncSession: ...  # RuntimeError, если unit_of_work не открыт
```

- **REST**: dependency `db_unit_of_work` = `async with unit_of_work(): yield`, подключается к
  роутерам с `Depends(..., scope="function")` — коммит завершается до отправки ответа.
- **MCP**: middleware `MCPServer` на `tools/call` (ADR-0010) — не ASGI-middleware, потому что
  HTTP-запрос может завершиться раньше обработчика, стримящего ответ через SSE —
  вызывает тот же `unit_of_work()` вокруг тела инструмента.
- **Push-воркер**: `unit_of_work()` на каждую пачку строк outbox.
- **SSE**: эндпоинт открывает `unit_of_work()` только на время проверки аутентификации,
  сам поток идёт без сессии.
- Своего механизма «после коммита» в `unit_of_work` нет. Если действие должно выполняться только
  после успешного коммита (публикация события в SSE-хаб и сигнал push-воркеру, спец. §7, п. 2),
  оно делается через event listeners SQLAlchemy (`after_commit` сессии) — решается в плане,
  где появляется.
- Коммит делает **только** `unit_of_work`. Репозитории и сервисы могут вызывать `flush()`,
  но не `commit()` / `rollback()` (ADR-0005).
- Вложенный `unit_of_work` — ошибка. Если понадобится независимая транзакция внутри
  (например, запись попытки входа, которая должна пережить откат), это явный отдельный вызов
  `session_factory()`, а не второй `unit_of_work`.
- `session_factory` = `async_sessionmaker(engine, expire_on_commit=False)`; движок создаётся один
  раз в `lifespan`. Драйвер — `asyncpg`.

## Рассмотренные альтернативы

Подход — известный паттерн «сессия в `ContextVar`» + Unit of Work. Готовые реализации
рассмотрены и отклонены (сентябрь 2026):

- `advanced-alchemy` — коммитит после отправки ответа, ошибку коммита только логирует.
- `fastapi-sqla` — сессия в `request.state` и передаётся аргументами, не `ContextVar`;
  жёсткие верхние границы версий Python и FastAPI.
- `fastapi-async-sqlalchemy` — ближе всего, но коммитит в middleware, отсюда большой объём
  обработки краевых случаев (стриминг, фоновые задачи); MCP и воркер
  всё равно требуют явного контекста.
- `context-async-sqlalchemy` — разрешает коммит из обработчика, небольшое сообщество.

Свой модуль — ~40 строк: коммит в dependency со `scope="function"` снимает краевые случаи
middleware, а явный `unit_of_work()` одинаково работает для REST, MCP и воркера.

## Последствия

- Репозитории берут сессию через `get_current_session()` (ADR-0005). Сервисы тоже могут
  вызывать его для запросов, которые не укладываются в репозиторий (массовые операции,
  отчёты), — по тем же правилам: без `commit()` / `rollback()`.
- Вызов репозитория вне `unit_of_work` падает сразу и громко, а не молча открывает новую сессию.
- Тесты подменяют `session_factory` на привязанную к внешней транзакции (ADR-0011).

## Как проверяется

- Тесты `db/session.py`: коммит при успехе, откат при исключении, ошибка при вложенности,
  сброс контекста после выхода.
- Тест REST: ответ отправляется после коммита (ошибка коммита → 500, а не 200).
- `scripts/check_transactions.py` в `scripts/lint.sh`: AST-проверка запрещает вызовы
  `.commit()` / `.rollback()` в исходниках приложения вне `db/session.py`.
