# Архитектурные решения (ADR)

Как и зачем ведутся — [ADR-0000](0000-record-architecture-decisions.md). Перед работой над модулем
прочитайте относящиеся к нему ADR; «что делает система» — в [спецификации](../superpowers/specs/2026-09-29-grocery-list-design.md).

| № | Решение | Статус |
|---|---|---|
| [0000](0000-record-architecture-decisions.md) | Фиксируем архитектурные решения в ADR | принято |
| [0001](0001-modular-monolith.md) | Модульный монолит с фиксированным направлением зависимостей | принято |
| [0002](0002-pydantic-and-strict-typing.md) | Pydantic-схемы на границах и строгая типизация | принято |
| [0003](0003-current-user-and-source.md) | Текущий пользователь в контексте, источник — явным аргументом | принято |
| [0004](0004-db-session-per-unit-of-work.md) | Одна сессия БД на единицу работы в `ContextVar` | принято |
| [0005](0005-repositories.md) | Репозитории со стандартным набором методов | принято |
| [0006](0006-settings.md) | Конфигурация — pydantic-settings в одном модуле | принято |
| [0007](0007-tooling.md) | Инструменты: uv, ruff, mypy, pytest, pre-commit; скрипты проверок | принято |
| [0008](0008-business-logic-in-shopping-list-service.md) | Бизнес-логика только в `shopping_list_service`; REST и MCP — адаптеры | принято |
| [0009](0009-typed-frontend-contract.md) | Типизированный контракт фронтенд ↔ бэкенд через OpenAPI | принято |
| [0010](0010-auth.md) | Аутентификация: свой OAuth AS (CIMD + DCR), `mcp` SDK как resource server, PAT, cookie | принято |
| [0011](0011-tests-on-real-postgres.md) | Тесты сервисов и адаптеров — на реальном Postgres | принято |
| [0012](0012-domain-errors.md) | Доменные ошибки и их перевод в REST и MCP | принято |
| [0013](0013-orm-model-conventions.md) | Соглашения ORM-моделей и миграций (enum без нативного типа) | принято |
| [0014](0014-repository-structure.md) | Структура репозитория и пакетов | принято |
