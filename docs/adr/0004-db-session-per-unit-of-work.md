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
_after_commit: ContextVar[list[Callable[[], Awaitable[None]]] | None] = ...

@asynccontextmanager
async def unit_of_work() -> AsyncIterator[AsyncSession]:
    """Открыть сессию, выставить её в контекст, закоммитить при успехе."""
    if _session.get() is not None:
        raise RuntimeError("unit_of_work уже открыт в этом контексте")
    async with session_factory() as session:
        s_token, h_token = _session.set(session), _after_commit.set([])
        try:
            yield session
            await session.commit()
            hooks = _after_commit.get() or []
        except BaseException:
            await session.rollback()
            raise
        finally:
            _session.reset(s_token)
            _after_commit.reset(h_token)
    for hook in hooks:                      # после коммита, вне транзакции
        await hook()

def get_current_session() -> AsyncSession: ...  # RuntimeError, если unit_of_work не открыт
def on_commit(hook: Callable[[], Awaitable[None]]) -> None: ...
```

- **REST**: dependency `db_unit_of_work` = `async with unit_of_work(): yield`, подключается к
  роутерам с `Depends(..., scope="function")` — коммит завершается до отправки ответа.
- **MCP**: middleware `MCPServer` на `tools/call` (ADR-0010) — не ASGI-middleware, потому что
  HTTP-запрос может завершиться раньше обработчика, стримящего ответ через SSE —
  вызывает тот же `unit_of_work()` вокруг тела инструмента.
- **Push-воркер**: `unit_of_work()` на каждую пачку строк outbox.
- **SSE**: эндпоинт открывает `unit_of_work()` только на время проверки аутентификации,
  сам поток идёт без сессии.
- `on_commit` — механизм «после коммита»: модуль `events` регистрирует через него публикацию
  события в SSE-хаб и сигнал push-воркеру (спец. §7, п. 2). При откате хуки не вызываются.
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
  обработки краевых случаев (стриминг, фоновые задачи); нет хуков после коммита; MCP и воркер
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

- Тесты `db/session.py`: коммит при успехе, откат при исключении, хуки только после коммита,
  ошибка при вложенности, сброс контекста после выхода.
- Тест REST: ответ отправляется после коммита (ошибка коммита → 500, а не 200).
- Ruff-правило / grep в команде проверки: `.commit(` вне `db/session.py` запрещён.
