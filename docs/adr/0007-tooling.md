# ADR-0007. Инструменты: uv, ruff, mypy, pytest, pre-commit

Статус: принято · Дата: 2026-09-29

## Контекст

Правила из остальных ADR проверяются автоматически — линтерами, типами, тестами. Проверки должны
запускаться одинаково вручную, ассистентом, хуком перед коммитом и в CI.

## Решение

### Инструменты

- **Python 3.14** — `.python-version`, `requires-python = ">=3.14,<3.15"`. Встроенный
  `uuid.uuid7()` используется для первичных ключей (ADR-0013).
- **uv** — Python, зависимости, окружение. `pyproject.toml` + `uv.lock` в репозитории;
  зависимости для разработки — группа `dev` в `[dependency-groups]`. Всё запускается через `uv run`.
- **ruff** — линтер и форматтер. Длина строки 100. Правила:
  `E, W, F, I, UP, B, SIM, ASYNC, N, RUF, TID, S, PT, DTZ, FAST`
  (`S` — безопасность, `DTZ` — только timezone-aware даты, `TID251` — запрещённые API из других
  ADR, `FAST` — правила FastAPI). В тестах отключён `S101` (`assert`). `ANN` не включаем —
  аннотации уже требует mypy strict.
- **mypy** — `strict = true`, плагин `pydantic.mypy` (ADR-0002).
- **import-linter** — слои и границы модулей (ADR-0001, ADR-0005, ADR-0008).
- **pytest** + `pytest-asyncio` (`asyncio_mode = "auto"`,
  `asyncio_default_fixture_loop_scope = "session"` — движок БД и контейнер живут в одном цикле
  событий с тестами), `testcontainers[postgres]`, `httpx`, `pytest-cov` (отчёт без порога).

### Скрипты — единственное место, где записаны команды

```
scripts/
  fmt.sh         ruff format + ruff check --fix
  lint.sh        ruff format --check + ruff check + lint-imports
  typecheck.sh   mypy
  test.sh        pytest (аргументы пробрасываются: scripts/test.sh -k merge)
  api.sh         экспорт OpenAPI + генерация TS-типов (ADR-0009)
  check.sh       lint + typecheck + test + проверка, что api.sh ничего не меняет
```

- Скрипты — `bash`, начинаются с `set -euo pipefail`, работают из любой директории
  (переходят в корень репозитория сами), вызывают инструменты через `uv run`.
- **Makefile** — тонкая обёртка для удобства: `make fmt`, `make lint`, `make check`, … — каждая
  цель вызывает одноимённый скрипт, своей логики нет.
- **CI** вызывает те же скрипты (`scripts/check.sh`), а не дублирует команды в YAML.
  Устройство CI/CD — отдельный ADR (открытый вопрос спец. §13).
- Фронтенд добавит свои шаги (`tsc --noEmit`, ESLint, Prettier) в `lint.sh` / `typecheck.sh`
  при создании `frontend/`.

### pre-commit

`.pre-commit-config.yaml`, быстрые проверки на каждый коммит:

- `ruff-format`, `ruff-check --fix` (`astral-sh/ruff-pre-commit`);
- `uv-lock` — `uv.lock` соответствует `pyproject.toml` (`astral-sh/uv-pre-commit`);
- `gitleaks` — не даёт закоммитить секреты (`.env`, VAPID-ключи, токены `gl_pat_…`);
- гигиена из `pre-commit-hooks`: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`,
  `check-toml`, `check-added-large-files`, `check-merge-conflict`.

mypy и тесты в хук не входят — они медленные и запускаются `scripts/check.sh` перед пушем и в CI.
Установка: `uv run pre-commit install` (описано в README проекта).

## Последствия

- Код считается готовым, когда `scripts/check.sh` зелёный — это критерий и для ассистентов.
- Правило, которое можно выразить линтером, выражается линтером, а не пунктом ревью.
- Новая проверка добавляется в скрипт — и сразу работает локально, в `make` и в CI.

## Как проверяется

- `scripts/check.sh` в CI на каждый push.
- pre-commit в CI не дублируется: CI запускает `ruff` в `lint.sh`.
