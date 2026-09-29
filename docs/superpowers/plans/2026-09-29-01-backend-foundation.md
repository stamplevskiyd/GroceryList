# План 1. Фундамент бэкенда — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять Python-проект `grocery` со всеми проверками, настройками, единицей работы с БД, базовым репозиторием, миграциями, тестовой инфраструктурой на реальном Postgres, эндпоинтом `/api/health` и CI — так, чтобы следующие планы только добавляли предметную логику.

**Architecture:** Модульный монолит FastAPI (ADR-0001) со слоями `api | mcp_server → services → db → schemas → domain`, границы проверяет import-linter. Сессия SQLAlchemy живёт в `ContextVar` на время `unit_of_work()` (ADR-0004), репозитории берут её оттуда (ADR-0005). Тесты работают с Postgres в testcontainers, каждый тест изолирован внешней транзакцией с savepoint (ADR-0011).

**Tech Stack:** Python 3.14, uv ≥ 0.12, FastAPI ≥ 0.142, SQLAlchemy 2.1 (async) + asyncpg, Alembic 1.20, Pydantic 2.13, pydantic-settings 2.15, pytest 9 + pytest-asyncio 1.4 + testcontainers 4.15 + pytest-socket, ruff 0.16, mypy 2.3, import-linter 2.15, pre-commit 4.6, GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-09-29-grocery-list-design.md`](../specs/2026-09-29-grocery-list-design.md); правила — ADR в [`docs/adr/`](../../adr/README.md), особенно 0001, 0002, 0004, 0005, 0006, 0007, 0011, 0013, 0014, 0015.

## Global Constraints

- Python **3.14** (`requires-python = ">=3.14,<3.15"`), пакет **`grocery`** в src-layout: `backend/src/grocery/` (ADR-0007, ADR-0014).
- Слои и их имена — ровно `grocery.api`, `grocery.mcp_server`, `grocery.services`, `grocery.db`, `grocery.schemas`, `grocery.domain`; `grocery.config` и `grocery.main` вне слоёв (ADR-0001, ADR-0014).
- Коммитит **только** `unit_of_work()`; репозитории и сервисы — не больше `flush()` (ADR-0004, ADR-0005).
- Методы коллекций в репозиториях: `get_by_ids`, `add_all`, `delete_by_ids`; суффиксы `_list` / `_many` запрещены (ADR-0005).
- Настройки — только через `grocery.config.get_settings()`; имена переменных `<ГРУППА>_<ПОЛЕ>` с одним `_`; `os.environ` / `os.getenv` вне `config.py` запрещены ruff-правилом `TID251` (ADR-0006).
- Первичный ключ — `uuid7`, даты — `timestamptz`, имена ограничений — через `naming_convention`, каждая миграция содержит рабочий `downgrade` (ADR-0013).
- Образ Postgres — **`postgres:18-alpine`**, один тег для `docker-compose.yml` и testcontainers (ADR-0011).
- Все команды проверок — в `scripts/*.sh`; Makefile и CI только вызывают их (ADR-0007, ADR-0015).
- Тесты не ходят в сеть: `pytest-socket` (`--disable-socket --allow-unix-socket --allow-hosts=127.0.0.1,localhost,::1`) (ADR-0011).
- Строки для людей (сообщения ошибок, docstring'и, комментарии) — по-русски, как в ADR; идентификаторы и сообщения коммитов — по-английски.

## Review Focus

1. **База недоступна** (Postgres упал или ещё не поднялся) → `GET /api/health` отвечает `503` с `{"status": "unavailable", "version": ...}` быстро, а не `500` и не зависание — тест в Task 6.
2. **Хук после коммита упал** (например, публикация в SSE) → запрос, данные которого уже закоммичены, не превращается в ошибку; остальные хуки выполняются, сбой пишется в лог — тест в Task 4.
3. **Коллекция из нуля элементов** — `get_by_ids([])` → `[]`, `delete_by_ids([])` → `0` без SQL с пустым `IN ()` — тест в Task 5.
4. **Нарушение уникальности** (второй пользователь с тем же `username`) → `IntegrityError` поднимается из `add`, транзакция откатывается целиком, а не «тихо» теряется — тест в Task 5.
5. **Неполная конфигурация** (нет `DB_URL`) → приложение падает при чтении настроек с ошибкой, называющей поле, а не на первом запросе к БД — тест в Task 2.

## Файловая структура плана

```
GroceryList/
├── .github/workflows/ci.yml          Task 7
├── .gitignore                        Task 1 (дополняется)
├── .gitleaks.toml                    Task 1
├── .pre-commit-config.yaml           Task 1
├── .env.example                      Task 2
├── Makefile                          Task 1
├── README.md                         Task 7
├── docker-compose.yml                Task 7 (пока только postgres)
├── scripts/{fmt,lint,typecheck,test,check}.sh   Task 1
└── backend/
    ├── .python-version, pyproject.toml, uv.lock  Task 1
    ├── alembic.ini                   Task 3
    ├── migrations/env.py, script.py.mako, versions/2026_09_29_1200-0001_create_users.py   Task 3
    ├── src/grocery/
    │   ├── __init__.py, py.typed     Task 1
    │   ├── {api,mcp_server,services,db,schemas,domain}/__init__.py   Task 1
    │   ├── db/{repositories,models}/__init__.py   Task 1
    │   ├── config.py                 Task 2
    │   ├── db/base.py, db/models/user.py   Task 3
    │   ├── db/session.py             Task 4
    │   ├── db/repositories/base.py, db/repositories/users.py, schemas/users.py   Task 5
    │   ├── services/health.py, schemas/health.py, api/routers/health.py, main.py   Task 6
    └── tests/
        ├── support.py, conftest.py   Task 1, 3, 4
        ├── unit/test_layout.py, unit/test_config.py, unit/test_compose.py
        ├── migrations/test_migrations.py
        ├── integration/conftest.py, integration/test_session.py, integration/test_repository.py
        └── api/conftest.py, api/test_health.py, api/test_unit_of_work_dependency.py
```

Каталог `tests/migrations/` добавлен к структуре ADR-0014: миграционные тесты работают с отдельной пустой базой и не должны получать автоматическую изоляцию из `tests/integration/conftest.py`.

---

### Task 1: Каркас проекта, инструменты и скрипты проверок

**Files:**
- Create: `backend/.python-version`, `backend/pyproject.toml`, `backend/uv.lock` (генерируется)
- Create: `backend/src/grocery/__init__.py`, `backend/src/grocery/py.typed`
- Create: `backend/src/grocery/{api,mcp_server,services,db,schemas,domain}/__init__.py`, `backend/src/grocery/db/{repositories,models}/__init__.py`
- Create: `backend/tests/support.py`, `backend/tests/unit/test_layout.py`
- Create: `scripts/fmt.sh`, `scripts/lint.sh`, `scripts/typecheck.sh`, `scripts/test.sh`, `scripts/check.sh`
- Create: `Makefile`, `.pre-commit-config.yaml`, `.gitleaks.toml`, `.gitignore`

**Interfaces:**
- Consumes: —
- Produces: пакет `grocery` со слоями; `scripts/check.sh` (lint → typecheck → test); `tests/support.py` c `BACKEND_DIR: Path`, `REPO_ROOT: Path`, `POSTGRES_IMAGE: str`.

- [ ] **Step 1: Проверить uv**

Run: `uv --version`
Expected: `uv 0.12.x` или новее. Если старше — `brew upgrade uv` (hook `uv-lock` в pre-commit использует uv 0.12, lock-файлы должны совпадать по формату).

- [ ] **Step 2: Создать `backend/.python-version` и `backend/pyproject.toml`**

`backend/.python-version`:

```
3.14
```

`backend/pyproject.toml`:

```toml
[project]
name = "grocery"
version = "0.1.0"
description = "GroceryList backend: REST API, MCP server, OAuth"
requires-python = ">=3.14,<3.15"
dependencies = [
    "fastapi>=0.142",
    "uvicorn[standard]>=0.54",
    "sqlalchemy[asyncio]>=2.1.1",
    "asyncpg>=0.31",
    "alembic>=1.20",
    "pydantic>=2.13",
    "pydantic-settings>=2.15",
]

[dependency-groups]
dev = [
    "ruff>=0.16.9",
    "mypy>=2.3",
    "import-linter>=2.15",
    "shellcheck-py>=0.11",
    "pre-commit>=4.6",
    "pytest>=9.1",
    "pytest-asyncio>=1.4",
    "pytest-cov>=7.1",
    "pytest-socket>=0.8.1",
    "testcontainers>=4.15",
    "httpx>=0.28",
]

[build-system]
requires = ["uv_build>=0.12,<0.13"]
build-backend = "uv_build"

# ── ruff (ADR-0007) ────────────────────────────────────────────────────────────
[tool.ruff]
line-length = 100
target-version = "py314"
src = ["src", "."]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM", "ASYNC", "N", "RUF", "TID", "S", "PT", "DTZ", "FAST"]

[tool.ruff.lint.per-file-ignores]
# assert, тестовые пароли и чтение окружения в тестах допустимы
"tests/**" = ["S101", "S105", "S106", "TID251"]
# имена файлов миграций начинаются с даты
"migrations/versions/**" = ["N999"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"os.environ".msg = "Настройки читаются только через grocery.config.get_settings() (ADR-0006)"
"os.getenv".msg = "Настройки читаются только через grocery.config.get_settings() (ADR-0006)"

# ── mypy (ADR-0002) ────────────────────────────────────────────────────────────
[tool.mypy]
strict = true
python_version = "3.14"
plugins = ["pydantic.mypy"]
files = ["src", "tests", "migrations"]
# tests/ и migrations/ — не пакеты: имена модулей считаются от src/ и backend/,
# иначе несколько conftest.py конфликтуют.
explicit_package_bases = true
mypy_path = ["src", "."]
# Имена файлов миграций начинаются с даты и содержат «-» — это не имена модулей.
# Миграции проверяются stairway-тестом (ADR-0011).
exclude = ["^migrations/versions/"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true

# ── pytest (ADR-0011) ──────────────────────────────────────────────────────────
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
addopts = [
    "--import-mode=importlib",
    "--strict-markers",
    "--disable-socket",
    "--allow-unix-socket",
    "--allow-hosts=127.0.0.1,localhost,::1",
]
markers = [
    "real_commits: тест с настоящими коммитами; после него все таблицы очищаются TRUNCATE (ADR-0011)",
]

# ── import-linter (ADR-0001, ADR-0005, ADR-0008, ADR-0014) ─────────────────────
[tool.importlinter]
root_package = "grocery"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Слои: api | mcp_server → services → db → schemas → domain"
type = "layers"
layers = [
    "grocery.api | grocery.mcp_server",
    "grocery.services",
    "grocery.db",
    "grocery.schemas",
    "grocery.domain",
]

[[tool.importlinter.contracts]]
name = "Адаптеры не обращаются к репозиториям и моделям напрямую"
type = "forbidden"
source_modules = ["grocery.api", "grocery.mcp_server"]
forbidden_modules = ["grocery.db.repositories", "grocery.db.models"]
allow_indirect_imports = true

[[tool.importlinter.contracts]]
name = "Нижние слои не знают о веб-фреймворках и MCP SDK"
type = "forbidden"
source_modules = ["grocery.services", "grocery.db", "grocery.schemas", "grocery.domain"]
forbidden_modules = ["fastapi", "starlette", "mcp"]

[[tool.importlinter.contracts]]
name = "SQLAlchemy — только в данных и сервисах"
type = "forbidden"
source_modules = ["grocery.api", "grocery.mcp_server", "grocery.schemas", "grocery.domain"]
forbidden_modules = ["sqlalchemy"]
allow_indirect_imports = true
```

- [ ] **Step 3: Создать пакет и пустые слои**

```bash
cd backend
mkdir -p src/grocery/{api,mcp_server,services,db/repositories,db/models,schemas,domain} tests/unit
touch src/grocery/py.typed
for d in src/grocery src/grocery/api src/grocery/mcp_server src/grocery/services src/grocery/db \
         src/grocery/db/repositories src/grocery/db/models src/grocery/schemas src/grocery/domain; do
  : > "$d/__init__.py"
done
```

`backend/src/grocery/__init__.py` (перезаписать):

```python
"""GroceryList: список покупок с MCP-сервером."""
```

- [ ] **Step 4: Написать тест раскладки слоёв**

`backend/tests/support.py`:

```python
"""Общие константы тестов."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Тот же тег, что у сервиса postgres в docker-compose.yml (проверяет tests/unit/test_compose.py).
POSTGRES_IMAGE = "postgres:18-alpine"
```

`backend/tests/unit/test_layout.py`:

```python
"""Пакеты слоёв из ADR-0014 существуют и импортируются."""

import importlib

import pytest

LAYERS = [
    "grocery.api",
    "grocery.mcp_server",
    "grocery.services",
    "grocery.db",
    "grocery.db.repositories",
    "grocery.db.models",
    "grocery.schemas",
    "grocery.domain",
]


@pytest.mark.parametrize("module", LAYERS)
def test_layer_package_imports(module: str) -> None:
    assert importlib.import_module(module).__name__ == module
```

- [ ] **Step 5: Установить зависимости и запустить тест**

Run: `cd backend && uv sync && uv run pytest tests/unit -q`
Expected: `8 passed`. `uv sync` создаёт `backend/uv.lock` и `.venv`, при необходимости скачивает Python 3.14.

- [ ] **Step 6: Создать скрипты проверок**

`scripts/fmt.sh`:

```bash
#!/usr/bin/env bash
# Форматирование и автоисправления ruff (ADR-0007).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run ruff format .
uv run ruff check --fix .
```

`scripts/lint.sh`:

```bash
#!/usr/bin/env bash
# Линтеры: формат, правила ruff, границы слоёв, shell-скрипты (ADR-0007).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run ruff format --check .
uv run ruff check .
uv run lint-imports
uv run shellcheck ../scripts/*.sh
```

`scripts/typecheck.sh`:

```bash
#!/usr/bin/env bash
# Проверка типов: mypy strict (ADR-0002).
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run mypy
```

`scripts/test.sh`:

```bash
#!/usr/bin/env bash
# Тесты (ADR-0011). `scripts/test.sh unit` — только быстрые тесты без Docker;
# остальные аргументы передаются pytest: `scripts/test.sh -k merge`.
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [[ "${1:-}" == "unit" ]]; then
  shift
  exec uv run pytest tests/unit "$@"
fi
exec uv run pytest "$@"
```

`scripts/check.sh`:

```bash
#!/usr/bin/env bash
# Полная проверка: код готов, когда она зелёная (ADR-0007).
set -euo pipefail
here="$(dirname "$0")"
"$here/lint.sh"
"$here/typecheck.sh"
"$here/test.sh"
```

Run: `chmod +x scripts/*.sh`

- [ ] **Step 7: Создать Makefile**

`Makefile` (отступы — табуляция):

```make
# Тонкая обёртка над scripts/ (ADR-0007): своей логики здесь нет.
.PHONY: fmt lint typecheck test check

fmt lint typecheck check:
	./scripts/$@.sh

test:
	./scripts/test.sh $(ARGS)
```

- [ ] **Step 8: Проверить скрипты, в том числе запуск из другой директории**

Run: `make check`
Expected: ruff, lint-imports (`Contracts: 4 kept, 0 broken.`), shellcheck, mypy (`Success: no issues found`), pytest (`8 passed`) — всё зелёное.

Run: `repo="$(pwd)" && (cd /tmp && "$repo/scripts/lint.sh")`
Expected: тот же зелёный результат — скрипт сам переходит в `backend/`.

- [ ] **Step 9: Настроить pre-commit и gitleaks**

`.pre-commit-config.yaml`:

```yaml
# Быстрые проверки на каждый коммит (ADR-0007). mypy и тесты — в scripts/check.sh.
# Макеты Claude Design — снимок редактора, их не трогаем.
exclude: ^docs/design/screens/
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
      - id: check-merge-conflict
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.9
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.12.20
    hooks:
      - id: uv-lock
        files: ^backend/(pyproject\.toml|uv\.lock)$
        args: [--project, backend]
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
```

`.gitleaks.toml`:

```toml
# Правила gitleaks по умолчанию + исключение для шаблона окружения:
# в .env.example только заведомо не секретные значения для локальной разработки.
[extend]
useDefault = true

[[allowlists]]
description = "Шаблон переменных окружения без настоящих секретов"
paths = ['''^\.env\.example$''']
```

`.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/

# Секреты и локальное окружение (ADR-0006)
.env
deploy.env

# Node (фронтенд, план 7)
node_modules/
dist/

# ОС и редакторы
.DS_Store
.idea/
.vscode/
```

Run: `cd backend && uv run pre-commit install && uv run pre-commit run --all-files; cd ..`
Expected: все хуки `Passed`. Первый запуск дольше: pre-commit сам ставит Go и собирает gitleaks. Если `end-of-file-fixer` или `trailing-whitespace` исправили файлы в `docs/` — это ожидаемо при первом запуске: повторный `uv run pre-commit run --all-files` должен пройти без изменений.

- [ ] **Step 10: Commit**

```bash
git add backend/.python-version backend/pyproject.toml backend/uv.lock backend/src backend/tests \
        scripts Makefile .pre-commit-config.yaml .gitleaks.toml .gitignore
git add -u docs   # правки хуков гигиены, если были
git commit -m "Scaffold backend package, tooling and check scripts"
```

---

### Task 2: Настройки приложения

**Files:**
- Create: `backend/src/grocery/config.py`
- Create: `.env.example`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/unit/test_config.py`

**Interfaces:**
- Consumes: `tests/support.py: REPO_ROOT`
- Produces: `grocery.config.Settings` (группы `app: AppSettings`, `db: DbSettings`), `AppSettings.public_url: HttpUrl`, `AppSettings.version: str = "dev"`, `AppSettings.log_level: str = "INFO"`, `DbSettings.url: PostgresDsn`; `get_settings() -> Settings` (кэш, `get_settings.cache_clear()`). Корневой `tests/conftest.py` задаёт минимальное окружение и сбрасывает кэш настроек вокруг каждого теста.

- [ ] **Step 1: Написать корневой conftest с минимальным окружением**

`backend/tests/conftest.py`:

```python
"""Общие фикстуры тестов (ADR-0011)."""

import os
from collections.abc import Iterator

import pytest

from grocery.config import get_settings


def pytest_configure(config: pytest.Config) -> None:
    # Минимальное окружение для Settings. Настоящая БД тестам не нужна: фабрика сессий
    # подменяется фикстурами, поэтому DB_URL указывает на заведомо закрытый порт.
    os.environ.setdefault("APP_PUBLIC_URL", "http://testserver")
    os.environ.setdefault("DB_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

- [ ] **Step 2: Написать падающие тесты настроек**

`backend/tests/unit/test_config.py`:

```python
"""Настройки: переменные <ГРУППА>_<ПОЛЕ>, ошибки конфигурации, .env.example (ADR-0006)."""

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from grocery.config import Settings, get_settings
from tests.support import REPO_ROOT


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Settings читает .env из рабочей директории — изолируемся от локального файла разработчика.
    monkeypatch.chdir(tmp_path)


def test_reads_groups_with_single_underscore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", "https://grocery.example")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:secret@db:5432/grocery")

    settings = Settings()

    assert settings.app.public_url.host == "grocery.example"
    assert settings.app.log_level == "DEBUG"
    assert settings.app.version == "dev"
    assert settings.db.url.hosts()[0]["host"] == "db"


def test_missing_group_names_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "db" in {error["loc"][0] for error in exc_info.value.errors()}


def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_URL", "not a url")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert ("app", "public_url") in {error["loc"] for error in exc_info.value.errors()}


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def _env_names() -> list[str]:
    names = []
    for group_name, group_field in Settings.model_fields.items():
        group_model = group_field.annotation
        assert isinstance(group_model, type)
        assert issubclass(group_model, BaseModel)
        names += [f"{group_name}_{field}".upper() for field in group_model.model_fields]
    return names


def test_group_names_have_no_underscore() -> None:
    # env_nested_max_split=1 делит имя по первому «_» — в имени группы его быть не должно.
    assert all("_" not in group for group in Settings.model_fields)


def test_env_example_lists_every_setting() -> None:
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    declared = {line.split("=", 1)[0] for line in lines if "=" in line and not line.startswith("#")}

    assert set(_env_names()) <= declared
```

- [ ] **Step 3: Запустить тесты — убедиться, что падают**

Run: `scripts/test.sh unit -k config`
Expected: ошибка сбора — `ModuleNotFoundError: No module named 'grocery.config'`.

- [ ] **Step 4: Реализовать `config.py`**

`backend/src/grocery/config.py`:

```python
"""Настройки приложения — единственное место чтения окружения (ADR-0006).

Имена переменных: <ГРУППА>_<ПОЛЕ>, например DB_URL → settings.db.url.
"""

from functools import lru_cache

from pydantic import BaseModel, HttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    public_url: HttpUrl
    version: str = "dev"
    log_level: str = "INFO"


class DbSettings(BaseModel):
    url: PostgresDsn


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Из backend/ читается .env в корне репозитория; в контейнере переменные приходят
        # из окружения, файла нет.
        env_file=("../.env", ".env"),
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="ignore",
    )

    app: AppSettings
    db: DbSettings


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Создать `.env.example`**

`.env.example` (в корне репозитория):

```dotenv
# Скопируйте в .env и заполните. Имена: <ГРУППА>_<ПОЛЕ> (ADR-0006).
# Все переменные Settings должны быть перечислены здесь (проверяет tests/unit/test_config.py).

# Публичный адрес приложения: от него зависят OAuth-метаданные и адрес MCP.
APP_PUBLIC_URL=http://localhost:8000
# Версия; в образе задаётся при сборке (ADR-0015).
APP_VERSION=dev
APP_LOG_LEVEL=INFO

# Postgres. Для `uv run` на машине разработчика — localhost; внутри docker compose — postgres.
DB_URL=postgresql+asyncpg://grocery:grocery@localhost:5432/grocery

# Для контейнера postgres в docker-compose.yml.
POSTGRES_USER=grocery
POSTGRES_PASSWORD=grocery
POSTGRES_DB=grocery
```

- [ ] **Step 6: Запустить тесты — убедиться, что проходят**

Run: `scripts/test.sh unit -k config`
Expected: `6 passed`.

- [ ] **Step 7: Полная проверка и commit**

Run: `scripts/check.sh`
Expected: зелёный.

```bash
git add backend/src/grocery/config.py backend/tests/conftest.py backend/tests/unit/test_config.py .env.example
git commit -m "Add settings with nested env groups"
```

---

### Task 3: ORM-база, модель `User`, Alembic и тесты миграций

**Files:**
- Create: `backend/src/grocery/db/base.py`, `backend/src/grocery/db/models/user.py`
- Modify: `backend/src/grocery/db/models/__init__.py`
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/2026_09_29_1200-0001_create_users.py`
- Modify: `backend/tests/conftest.py` (фикстуры Postgres), `backend/tests/support.py` (конфиг Alembic)
- Test: `backend/tests/migrations/test_migrations.py`

**Interfaces:**
- Consumes: `grocery.config.get_settings()` (URL БД для CLI Alembic)
- Produces:
  - `grocery.db.base.Base` (`DeclarativeBase` c `naming_convention`), `grocery.db.base.Entity` (абстрактный: `id: Mapped[UUID]` c `default=uuid7`, `created_at`, `updated_at: Mapped[datetime]` timestamptz, `eager_defaults=True`), `NAMING_CONVENTION: dict[str, str]`.
  - `grocery.db.models.User` (`users`: `username: str` уникальный, до 64 символов; `password_hash: str`).
  - `tests/support.py: alembic_config(database_url: str) -> alembic.config.Config`.
  - Фикстуры `postgres` (session, `PostgresContainer`), `database_url` (session, `str`, база уже на `head`).
  - Ревизии нумеруются подряд: `0001`, `0002`, … (`alembic revision --rev-id`).

- [ ] **Step 1: Добавить фикстуры Postgres и помощник Alembic**

Дописать в `backend/tests/support.py`:

```python
from alembic.config import Config


def alembic_config(database_url: str) -> Config:
    """Конфиг Alembic, нацеленный на указанную базу."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # configparser трактует «%» как интерполяцию.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config
```

(импорт `from alembic.config import Config` поднять к остальным импортам в начале файла.)

Дописать в `backend/tests/conftest.py`:

```python
from collections.abc import Iterator

from alembic import command
from testcontainers.community.postgres import PostgresContainer

from tests.support import POSTGRES_IMAGE, alembic_config


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    """URL основной тестовой базы; схема создаётся миграциями, а не create_all (ADR-0011)."""
    url = postgres.get_connection_url()
    command.upgrade(alembic_config(url), "head")
    return url
```

(импорты объединить с существующими в начале файла; `Iterator` уже импортирован.)

- [ ] **Step 2: Написать падающие тесты миграций**

`backend/tests/migrations/test_migrations.py`:

```python
"""Миграции: совпадение с моделями и stairway-тест (ADR-0011, ADR-0013).

Тесты синхронные: env.py Alembic сам запускает asyncio.run().
"""

import asyncio

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from tests.support import alembic_config

DATABASE = "migrations_check"


async def _recreate_database(admin_url: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text('DROP DATABASE IF EXISTS "migrations_check"'))
        await connection.execute(text('CREATE DATABASE "migrations_check"'))
    await engine.dispose()


@pytest.fixture
def empty_database_url(postgres: PostgresContainer) -> str:
    """Отдельная пустая база в том же контейнере — не мешает основной тестовой."""
    admin_url = postgres.get_connection_url()
    asyncio.run(_recreate_database(admin_url))
    return make_url(admin_url).set(database=DATABASE).render_as_string(hide_password=False)


def test_upgrade_head_matches_models(empty_database_url: str) -> None:
    config = alembic_config(empty_database_url)

    command.upgrade(config, "head")

    # AutogenerateDiffsDetected, если модели и миграции разошлись.
    command.check(config)


def test_stairway(empty_database_url: str) -> None:
    config = alembic_config(empty_database_url)
    revisions = list(ScriptDirectory.from_config(config).walk_revisions("base", "heads"))

    assert revisions, "нет ни одной миграции"
    for revision in reversed(revisions):
        command.upgrade(config, revision.revision)
        command.downgrade(config, "-1")
        command.upgrade(config, revision.revision)
```

- [ ] **Step 3: Запустить — убедиться, что падают**

Run: `scripts/test.sh tests/migrations -q`
Expected: FAIL — `alembic.util.exc.CommandError` (нет `alembic.ini` / `script_location`). Первый запуск скачивает образ `postgres:18-alpine`; нужен запущенный Docker.

- [ ] **Step 4: Реализовать базовые классы моделей**

`backend/src/grocery/db/base.py`:

```python
"""Базовые классы ORM-моделей (ADR-0013)."""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID, uuid7

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Стабильные имена ограничений — чтобы Alembic мог их удалять и переименовывать.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Entity(Base):
    """Таблица-сущность: ключ UUIDv7 и метки времени. Таблицы связей наследуют Base."""

    __abstract__ = True
    # Значения server_default / onupdate сразу забираются через RETURNING: иначе чтение
    # created_at / updated_at после flush вызвало бы неявный запрос, запрещённый в async.
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: Реализовать модель `User`**

`backend/src/grocery/db/models/user.py`:

```python
"""Пользователь (спец. §4)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from grocery.db.base import Entity


class User(Entity):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
```

`backend/src/grocery/db/models/__init__.py`:

```python
"""Все ORM-модели. Импорт пакета регистрирует их в Base.metadata (нужно Alembic)."""

from grocery.db.models.user import User

__all__ = ["User"]
```

- [ ] **Step 6: Настроить Alembic**

`backend/alembic.ini`:

```ini
[alembic]
script_location = %(here)s/migrations
# Имя файла миграции начинается с даты: 2026_09_29_1200-0001_create_users.py (ADR-0013).
file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s
prepend_sys_path = .
path_separator = os
timezone = UTC
# URL не задаётся здесь: env.py берёт его из настроек (DB_URL), тесты подставляют свой.
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`backend/migrations/env.py`:

```python
"""Alembic: асинхронные миграции (ADR-0013)."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from grocery.config import get_settings
from grocery.db import models  # noqa: F401 — регистрирует модели в Base.metadata
from grocery.db.base import Base

config = context.config
target_metadata = Base.metadata

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", str(get_settings().db.url).replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

`backend/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 7: Сгенерировать первую миграцию и привести её к эталону**

Autogenerate требует живую базу. Поднять временный Postgres и сгенерировать:

```bash
docker run -d --rm --name grocery-autogen -e POSTGRES_PASSWORD=x -p 127.0.0.1:55432:5432 postgres:18-alpine
sleep 3
cd backend
DB_URL=postgresql+asyncpg://postgres:x@127.0.0.1:55432/postgres APP_PUBLIC_URL=http://localhost \
  uv run alembic revision --autogenerate --rev-id 0001 -m "create users"
cd .. && docker stop grocery-autogen
```

Проверить сгенерированный `backend/migrations/versions/2026_09_29_*-0001_create_users.py` и привести содержимое к эталону (имя файла оставить сгенерированным):

```python
"""create users

Revision ID: 0001
Revises:
Create Date: 2026-09-29 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )


def downgrade() -> None:
    op.drop_table("users")
```

- [ ] **Step 8: Запустить тесты миграций — убедиться, что проходят**

Run: `scripts/test.sh tests/migrations -q`
Expected: `2 passed`.

- [ ] **Step 9: Полная проверка и commit**

Run: `scripts/check.sh`
Expected: зелёный (mypy проверяет и `migrations/`).

```bash
git add backend/src/grocery/db backend/alembic.ini backend/migrations backend/tests
git commit -m "Add ORM base, users table and migration tests"
```

---

### Task 4: Единица работы (`db/session.py`) и изоляция тестов

**Files:**
- Create: `backend/src/grocery/db/session.py`
- Modify: `backend/tests/conftest.py` (фикстуры `engine`, `db`)
- Create: `backend/tests/integration/conftest.py`
- Test: `backend/tests/integration/test_session.py`

**Interfaces:**
- Consumes: `grocery.db.models.User`, фикстура `database_url`
- Produces (`grocery.db.session`):
  - `configure_engine(url: str) -> AsyncEngine`, `async dispose_engine() -> None`
  - `override_session_factory(factory: async_sessionmaker[AsyncSession]) -> ContextManager[None]` — только для тестов
  - `unit_of_work() -> AsyncContextManager[AsyncSession]` — коммит при успехе, откат при исключении, `RuntimeError` при вложенности
  - `get_current_session() -> AsyncSession` — `RuntimeError` вне `unit_of_work`
  - `on_commit(hook: AfterCommitHook) -> None`, `type AfterCommitHook = Callable[[], Awaitable[None]]` — хуки выполняются после коммита, по порядку; упавший хук логируется и не прерывает остальные
- Фикстуры: `engine` (session, `AsyncEngine`), `db` (function; savepoint-изоляция или, с маркером `real_commits`, настоящие коммиты + `TRUNCATE`). В `tests/integration/` `db` подключается автоматически.

- [ ] **Step 1: Добавить фикстуры изоляции**

Дописать в `backend/tests/conftest.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from grocery.db import models  # noqa: F401 — все таблицы в Base.metadata для TRUNCATE
from grocery.db.base import Base
from grocery.db.session import override_session_factory


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


async def _truncate_all(engine: AsyncEngine) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        # Имена таблиц берутся из metadata, а не из ввода.
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))  # noqa: S608


@pytest.fixture
async def db(engine: AsyncEngine, request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Изоляция теста (ADR-0011).

    По умолчанию — внешняя транзакция: commit() в unit_of_work фиксирует только savepoint,
    после теста всё откатывается. С маркером real_commits — обычные коммиты и TRUNCATE после.
    """
    if request.node.get_closest_marker("real_commits"):
        with override_session_factory(async_sessionmaker(engine, expire_on_commit=False)):
            yield
        await _truncate_all(engine)
        return

    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        with override_session_factory(factory):
            yield
        await transaction.rollback()
```

`backend/tests/integration/conftest.py`:

```python
"""Интеграционные тесты: каждый изолирован фикстурой db."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None
```

- [ ] **Step 2: Написать падающие тесты единицы работы**

`backend/tests/integration/test_session.py`:

```python
"""unit_of_work: коммит, откат, контекст, хуки после коммита (ADR-0004)."""

import logging

import pytest
from sqlalchemy import func, select

from grocery.db.models import User
from grocery.db.session import get_current_session, on_commit, unit_of_work


async def _count_users() -> int:
    async with unit_of_work() as session:
        return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_commits_on_success() -> None:
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))

    assert await _count_users() == 1


async def test_rolls_back_on_exception() -> None:
    with pytest.raises(ValueError, match="boom"):
        async with unit_of_work() as session:
            session.add(User(username="anna", password_hash="h"))
            await session.flush()
            raise ValueError("boom")

    assert await _count_users() == 0


async def test_current_session_is_the_unit_of_work_session() -> None:
    async with unit_of_work() as session:
        assert get_current_session() is session


async def test_current_session_outside_unit_of_work_raises() -> None:
    with pytest.raises(RuntimeError, match="unit_of_work"):
        get_current_session()


async def test_context_is_reset_after_exit() -> None:
    async with unit_of_work():
        pass

    with pytest.raises(RuntimeError, match="unit_of_work"):
        get_current_session()


async def test_nested_unit_of_work_raises() -> None:
    async with unit_of_work():
        with pytest.raises(RuntimeError, match="уже открыт"):
            async with unit_of_work():
                pass


async def test_hooks_run_after_commit_in_order() -> None:
    calls: list[str] = []

    async def first() -> None:
        # Хук выполняется вне единицы работы и видит закоммиченные данные.
        calls.append(f"first:{await _count_users()}")

    async def second() -> None:
        calls.append("second")

    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))
        on_commit(first)
        on_commit(second)
        assert calls == []

    assert calls == ["first:1", "second"]


async def test_hooks_do_not_run_on_rollback() -> None:
    calls: list[str] = []

    async def hook() -> None:
        calls.append("called")

    with pytest.raises(ValueError, match="boom"):
        async with unit_of_work():
            on_commit(hook)
            raise ValueError("boom")

    assert calls == []


async def test_failing_hook_is_logged_and_others_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    async def failing() -> None:
        raise RuntimeError("sse down")

    async def next_hook() -> None:
        calls.append("next")

    with caplog.at_level(logging.ERROR, logger="grocery.db.session"):
        async with unit_of_work():
            on_commit(failing)
            on_commit(next_hook)

    assert calls == ["next"]
    assert "sse down" in caplog.text


async def test_on_commit_outside_unit_of_work_raises() -> None:
    async def hook() -> None:
        return None

    with pytest.raises(RuntimeError, match="unit_of_work"):
        on_commit(hook)
```

- [ ] **Step 3: Запустить — убедиться, что падают**

Run: `scripts/test.sh tests/integration -q`
Expected: ошибка сбора — `ModuleNotFoundError: No module named 'grocery.db.session'`.

- [ ] **Step 4: Реализовать `db/session.py`**

`backend/src/grocery/db/session.py`:

```python
"""Сессия БД на единицу работы, хранится в ContextVar (ADR-0004).

Единственное место, где создаются сессии и делается commit. Единицу работы открывают:
dependency REST, middleware MCP, push-воркер.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

type AfterCommitHook = Callable[[], Awaitable[None]]

_session: ContextVar[AsyncSession | None] = ContextVar("db_session", default=None)
_after_commit: ContextVar[list[AfterCommitHook] | None] = ContextVar(
    "db_after_commit", default=None
)


class _Database:
    engine: AsyncEngine | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None


_database = _Database()


def configure_engine(url: str) -> AsyncEngine:
    """Создать движок и фабрику сессий. Вызывается один раз в lifespan приложения."""
    engine = create_async_engine(url, pool_pre_ping=True)
    _database.engine = engine
    _database.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine


async def dispose_engine() -> None:
    if _database.engine is not None:
        await _database.engine.dispose()
    _database.engine = None
    _database.session_factory = None


@contextmanager
def override_session_factory(factory: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    """Подменить фабрику сессий — только для тестов (ADR-0011)."""
    previous = _database.session_factory
    _database.session_factory = factory
    try:
        yield
    finally:
        _database.session_factory = previous


def _session_factory() -> async_sessionmaker[AsyncSession]:
    if _database.session_factory is None:
        raise RuntimeError("БД не настроена: configure_engine() не вызывался")
    return _database.session_factory


@asynccontextmanager
async def unit_of_work() -> AsyncIterator[AsyncSession]:
    """Открыть сессию в контексте; закоммитить при успехе, откатить при исключении.

    Хуки on_commit выполняются после коммита, вне транзакции. Упавший хук логируется и не
    превращает уже сохранённое изменение в ошибку.
    """
    if _session.get() is not None:
        raise RuntimeError("unit_of_work уже открыт в этом контексте")
    hooks: list[AfterCommitHook] = []
    async with _session_factory()() as session:
        session_token = _session.set(session)
        hooks_token = _after_commit.set(hooks)
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            _session.reset(session_token)
            _after_commit.reset(hooks_token)
    for hook in hooks:
        try:
            await hook()
        except Exception:
            logger.exception("Хук после коммита завершился ошибкой; данные уже сохранены")


def get_current_session() -> AsyncSession:
    session = _session.get()
    if session is None:
        raise RuntimeError("Сессия БД не открыта: вызов вне unit_of_work")
    return session


def on_commit(hook: AfterCommitHook) -> None:
    """Выполнить hook после успешного коммита текущей единицы работы."""
    hooks = _after_commit.get()
    if hooks is None:
        raise RuntimeError("on_commit вызван вне unit_of_work")
    hooks.append(hook)
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `scripts/test.sh tests/integration -q`
Expected: `10 passed`.

- [ ] **Step 6: Полная проверка и commit**

Run: `scripts/check.sh`
Expected: зелёный.

```bash
git add backend/src/grocery/db/session.py backend/tests
git commit -m "Add unit of work with ContextVar session and test isolation"
```

---

### Task 5: Базовый репозиторий и `UserRepository`

**Files:**
- Create: `backend/src/grocery/db/repositories/base.py`, `backend/src/grocery/db/repositories/users.py`
- Create: `backend/src/grocery/schemas/users.py`
- Test: `backend/tests/integration/test_repository.py`

**Interfaces:**
- Consumes: `grocery.db.session.get_current_session()`, `grocery.db.base.Entity`, `grocery.db.models.User`
- Produces:
  - `grocery.db.repositories.base.Repository[M: Entity, C: BaseModel, U: BaseModel]`: `__init__(model: type[M])`; `exclude_on_write: ClassVar[frozenset[str]]`; `async get(id: UUID) -> M | None`; `async get_by_ids(ids: Sequence[UUID]) -> list[M]`; `async add(data: C, **extra: Any) -> M`; `async add_all(items: Sequence[C], **extra: Any) -> list[M]`; `async update(obj: M, data: U) -> M` (только явно переданные поля); `async delete(obj: M) -> None`; `async delete_by_ids(ids: Sequence[UUID]) -> int`.
  - `add` / `add_all` пишут обычные **и вычисляемые** (`computed_field`) поля схемы, кроме `exclude_on_write`; вложенные Pydantic-объекты передаются как объекты (для `PydanticJSON` в плане 2).
  - `grocery.schemas.users.UserCreate(username: str, password_hash: str)`, `UserUpdate(username: str | None = None, password_hash: str | None = None)`.
  - `grocery.db.repositories.users.UserRepository`, экземпляр `user_repo`.

- [ ] **Step 1: Написать схемы пользователя**

`backend/src/grocery/schemas/users.py`:

```python
"""Схемы пользователя для репозитория. Регистрации через API нет (спец. §6.1)."""

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password_hash: str


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password_hash: str | None = None
```

- [ ] **Step 2: Написать падающие тесты репозитория**

`backend/tests/integration/test_repository.py`:

```python
"""Базовый репозиторий: стандартные методы на примере пользователей (ADR-0005)."""

from typing import ClassVar
from uuid import uuid7

import pytest
from pydantic import BaseModel, computed_field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from grocery.db.models import User
from grocery.db.repositories.base import Repository
from grocery.db.repositories.users import user_repo
from grocery.db.session import unit_of_work
from grocery.schemas.users import UserCreate, UserUpdate


def _user(name: str) -> UserCreate:
    return UserCreate(username=name, password_hash=f"hash-{name}")


async def test_add_returns_persisted_object_with_uuid7_and_timestamps() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))

        assert user.id.version == 7
        assert user.created_at.tzinfo is not None
        assert user.updated_at.tzinfo is not None

    async with unit_of_work():
        stored = await user_repo.get(user.id)
        assert stored is not None
        assert stored.username == "anna"


async def test_add_accepts_extra_fields() -> None:
    class UsernameOnly(BaseModel):
        username: str

    class UsernameOnlyRepository(Repository[User, UsernameOnly, UserUpdate]):
        pass

    async with unit_of_work():
        user = await UsernameOnlyRepository(User).add(
            UsernameOnly(username="anna"), password_hash="from-service"
        )

    assert user.password_hash == "from-service"


async def test_add_writes_computed_fields_and_skips_excluded() -> None:
    class LoginCreate(BaseModel):
        login: str
        password_hash: str

        @computed_field
        @property
        def username(self) -> str:
            return self.login.strip().lower()

    class LoginRepository(Repository[User, LoginCreate, UserUpdate]):
        exclude_on_write: ClassVar[frozenset[str]] = frozenset({"login"})

    async with unit_of_work():
        user = await LoginRepository(User).add(LoginCreate(login="  Anna ", password_hash="h"))

    assert user.username == "anna"


async def test_add_all() -> None:
    async with unit_of_work():
        users = await user_repo.add_all([_user("anna"), _user("boris")])

    assert [user.username for user in users] == ["anna", "boris"]
    assert all(user.id is not None for user in users)


async def test_get_missing_returns_none() -> None:
    async with unit_of_work():
        assert await user_repo.get(uuid7()) is None


async def test_get_by_ids_returns_only_existing() -> None:
    async with unit_of_work():
        anna, boris = await user_repo.add_all([_user("anna"), _user("boris")])
        found = await user_repo.get_by_ids([anna.id, uuid7()])

    assert {user.id for user in found} == {anna.id}
    assert boris.id not in {user.id for user in found}


async def test_get_by_ids_with_empty_list() -> None:
    async with unit_of_work():
        assert await user_repo.get_by_ids([]) == []


async def test_update_changes_only_passed_fields() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))
        await user_repo.update(user, UserUpdate(password_hash="new-hash"))
        # updated_at доступен без неявного запроса (eager_defaults).
        assert user.updated_at is not None

    async with unit_of_work():
        stored = await user_repo.get(user.id)
        assert stored is not None
        assert (stored.username, stored.password_hash) == ("anna", "new-hash")


async def test_delete() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))
        await user_repo.delete(user)

    async with unit_of_work():
        assert await user_repo.get(user.id) is None


async def test_delete_by_ids_returns_count() -> None:
    async with unit_of_work():
        anna, boris, _ = await user_repo.add_all([_user("anna"), _user("boris"), _user("vera")])
        deleted = await user_repo.delete_by_ids([anna.id, boris.id, uuid7()])

    assert deleted == 2


async def test_delete_by_ids_with_empty_list() -> None:
    async with unit_of_work():
        assert await user_repo.delete_by_ids([]) == 0


async def test_duplicate_username_raises_and_rolls_back() -> None:
    async with unit_of_work():
        await user_repo.add(_user("anna"))

    with pytest.raises(IntegrityError):
        async with unit_of_work():
            await user_repo.add(_user("boris"))
            await user_repo.add(_user("anna"))

    # boris из упавшей единицы работы тоже не сохранился — откат целиком.
    async with unit_of_work() as session:
        names = set(await session.scalars(select(User.username)))
    assert names == {"anna"}


async def test_repository_outside_unit_of_work_raises() -> None:
    with pytest.raises(RuntimeError, match="unit_of_work"):
        await user_repo.add(_user("anna"))
```

- [ ] **Step 3: Запустить — убедиться, что падают**

Run: `scripts/test.sh tests/integration/test_repository.py -q`
Expected: ошибка сбора — `ModuleNotFoundError: No module named 'grocery.db.repositories.base'`.

- [ ] **Step 4: Реализовать базовый репозиторий**

`backend/src/grocery/db/repositories/base.py`:

```python
"""Базовый репозиторий: стандартный набор методов для всех моделей (ADR-0005).

Сессия берётся из контекста (ADR-0004); репозитории не коммитят.
"""

from collections.abc import Sequence
from typing import Any, ClassVar, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CursorResult, delete, select

from grocery.db.base import Entity
from grocery.db.session import get_current_session


def _values(data: BaseModel, *, exclude: frozenset[str], only_set: bool) -> dict[str, Any]:
    """Поля схемы для записи в модель.

    Вложенные Pydantic-объекты остаются объектами (их сериализует тип колонки), вычисляемые
    поля (computed_field) включаются — через них схемы передают нормализованные значения.
    """
    schema = type(data)
    if only_set:
        names = set(data.model_fields_set)
    else:
        names = set(schema.model_fields) | set(schema.model_computed_fields)
    return {name: getattr(data, name) for name in names - exclude}


class Repository[M: Entity, C: BaseModel, U: BaseModel]:
    # Поля схем, которые не пишутся в модель напрямую (например, связи).
    exclude_on_write: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, model: type[M]) -> None:
        self.model = model

    async def get(self, id: UUID) -> M | None:
        return await get_current_session().get(self.model, id)

    async def get_by_ids(self, ids: Sequence[UUID]) -> list[M]:
        if not ids:
            return []
        result = await get_current_session().scalars(
            select(self.model).where(self.model.id.in_(ids))
        )
        return list(result)

    async def add(self, data: C, **extra: Any) -> M:
        obj = self._build(data, extra)
        session = get_current_session()
        session.add(obj)
        await session.flush()
        return obj

    async def add_all(self, items: Sequence[C], **extra: Any) -> list[M]:
        objs = [self._build(data, extra) for data in items]
        session = get_current_session()
        session.add_all(objs)
        await session.flush()
        return objs

    async def update(self, obj: M, data: U) -> M:
        for field, value in _values(data, exclude=self.exclude_on_write, only_set=True).items():
            setattr(obj, field, value)
        await get_current_session().flush()
        return obj

    async def delete(self, obj: M) -> None:
        session = get_current_session()
        await session.delete(obj)
        await session.flush()

    async def delete_by_ids(self, ids: Sequence[UUID]) -> int:
        if not ids:
            return 0
        # execute() типизирован как Result; для DELETE это CursorResult с rowcount.
        result = cast(
            CursorResult[Any],
            await get_current_session().execute(
                delete(self.model).where(self.model.id.in_(ids))
            ),
        )
        return result.rowcount

    def _build(self, data: C, extra: dict[str, Any]) -> M:
        values = _values(data, exclude=self.exclude_on_write, only_set=False)
        return self.model(**values, **extra)
```

`backend/src/grocery/db/repositories/users.py`:

```python
"""Репозиторий пользователей."""

from grocery.db.models import User
from grocery.db.repositories.base import Repository
from grocery.schemas.users import UserCreate, UserUpdate


class UserRepository(Repository[User, UserCreate, UserUpdate]):
    pass


user_repo = UserRepository(User)
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `scripts/test.sh tests/integration/test_repository.py -q`
Expected: `13 passed`.

- [ ] **Step 6: Полная проверка и commit**

Run: `scripts/check.sh`
Expected: зелёный; lint-imports — `4 kept` (`db` импортирует `schemas`, что разрешено слоями).

```bash
git add backend/src/grocery/db/repositories backend/src/grocery/schemas/users.py backend/tests
git commit -m "Add generic CRUD repository and user repository"
```

---

### Task 6: Приложение FastAPI и `/api/health`

**Files:**
- Create: `backend/src/grocery/main.py`
- Create: `backend/src/grocery/api/deps.py`, `backend/src/grocery/api/routers/__init__.py`, `backend/src/grocery/api/routers/health.py`
- Create: `backend/src/grocery/services/health.py`, `backend/src/grocery/schemas/health.py`
- Create: `backend/tests/api/conftest.py`
- Test: `backend/tests/api/test_health.py`, `backend/tests/api/test_unit_of_work_dependency.py`

**Interfaces:**
- Consumes: `get_settings()`, `configure_engine`, `dispose_engine`, `unit_of_work`, `get_current_session`, `override_session_factory`
- Produces:
  - `grocery.main.create_app() -> FastAPI` (запуск: `uvicorn grocery.main:create_app --factory`); lifespan настраивает и закрывает движок БД.
  - `grocery.api.deps.DbUnitOfWork` — `Depends(..., scope="function")`, подключается к роутерам через `dependencies=[DbUnitOfWork]`; коммит завершается до отправки ответа.
  - `GET /api/health` → `200 {"status": "ok", "version": <APP_VERSION>}` или `503 {"status": "unavailable", "version": ...}`.
  - `grocery.services.health.database_is_available() -> bool`.
  - `grocery.schemas.health.HealthRead(status: Literal["ok", "unavailable"], version: str)`.
  - Фикстуры `app: FastAPI`, `client: httpx.AsyncClient`; в `tests/api/` `db` подключается автоматически.

- [ ] **Step 1: Написать фикстуры API-тестов**

`backend/tests/api/conftest.py`:

```python
"""API-тесты: приложение через ASGITransport, изоляция БД фикстурой db."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from grocery.main import create_app


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport не выполняет lifespan: движок БД подменяет фикстура db.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
```

- [ ] **Step 2: Написать падающие тесты `/api/health`**

`backend/tests/api/test_health.py`:

```python
"""GET /api/health — проверка для деплоя и healthcheck (ADR-0015)."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from grocery.config import get_settings
from grocery.db.session import override_session_factory


async def test_health_ok_reports_version(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_VERSION", "v1.2.3")
    get_settings.cache_clear()  # фикстура app уже прочитала настройки

    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "v1.2.3"}


async def test_health_is_public(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200


async def test_health_when_database_is_down_returns_503(client: httpx.AsyncClient) -> None:
    # Порт 1 на localhost закрыт — соединение отклоняется сразу.
    broken = create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/db")
    try:
        with override_session_factory(async_sessionmaker(broken)):
            response = await client.get("/api/health")
    finally:
        await broken.dispose()

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
```

- [ ] **Step 3: Написать падающий тест dependency единицы работы**

`backend/tests/api/test_unit_of_work_dependency.py`:

```python
"""DbUnitOfWork: сессия видна в обработчике, коммит — до ответа (ADR-0004)."""

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy import func, select

from grocery.api.deps import DbUnitOfWork
from grocery.db.models import User
from grocery.db.session import get_current_session, unit_of_work


def _add_probe_routes(app: FastAPI) -> None:
    router = APIRouter(dependencies=[DbUnitOfWork])

    @router.get("/probe/users/count")
    async def count_users() -> dict[str, int]:
        session = get_current_session()
        return {"count": await session.scalar(select(func.count()).select_from(User)) or 0}

    @router.post("/probe/users/{username}")
    async def add_user_without_flush(username: str) -> dict[str, str]:
        # Без flush: ошибка уникальности возникнет только при коммите в dependency.
        get_current_session().add(User(username=username, password_hash="h"))
        return {"status": "accepted"}

    app.include_router(router)


async def test_handler_sees_session_and_changes_are_committed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    _add_probe_routes(app)

    assert (await client.post("/probe/users/anna")).status_code == 200
    response = await client.get("/probe/users/count")

    assert response.json() == {"count": 1}


@pytest.mark.real_commits
async def test_commit_failure_is_reported_as_500(app: FastAPI) -> None:
    # В savepoint-режиме уникальность проверяется так же, но здесь важен настоящий COMMIT:
    # dependency со scope="function" должна завершить его до отправки ответа.
    _add_probe_routes(app)
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/probe/users/anna")

    assert response.status_code == 500
```

- [ ] **Step 4: Запустить — убедиться, что падают**

Run: `scripts/test.sh tests/api -q`
Expected: ошибка сбора — `ModuleNotFoundError: No module named 'grocery.main'`.

- [ ] **Step 5: Реализовать схему, сервис, dependency и роутер**

`backend/src/grocery/schemas/health.py`:

```python
"""Ответ /api/health."""

from typing import Literal

from pydantic import BaseModel


class HealthRead(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
```

`backend/src/grocery/services/health.py`:

```python
"""Проверка доступности БД для /api/health (ADR-0015)."""

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from grocery.db.session import unit_of_work

logger = logging.getLogger(__name__)


async def database_is_available() -> bool:
    """SELECT 1 в собственной единице работы.

    Исключение из правила «единицу работы открывает адаптер»: недоступная БД должна давать
    503, а не 500 из общей dependency.
    """
    try:
        async with unit_of_work() as session:
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        logger.warning("База данных недоступна", exc_info=True)
        return False
    return True
```

`backend/src/grocery/api/deps.py`:

```python
"""Общие dependency REST-адаптера."""

from collections.abc import AsyncIterator

from fastapi import Depends

from grocery.db.session import unit_of_work


async def _db_unit_of_work() -> AsyncIterator[None]:
    async with unit_of_work():
        yield


# scope="function": коммит завершается до отправки ответа — упавший коммит даёт 500,
# а не «200 OK» с потерянными данными (ADR-0004).
DbUnitOfWork = Depends(_db_unit_of_work, scope="function")
```

`backend/src/grocery/api/routers/__init__.py`:

```python
"""Роутеры REST API."""
```

`backend/src/grocery/api/routers/health.py`:

```python
"""GET /api/health — публичный эндпоинт для деплоя и healthcheck (ADR-0015)."""

from fastapi import APIRouter, Response, status

from grocery.config import get_settings
from grocery.schemas.health import HealthRead
from grocery.services import health as health_service

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthRead}},
)
async def health(response: Response) -> HealthRead:
    version = get_settings().app.version
    if not await health_service.database_is_available():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthRead(status="unavailable", version=version)
    return HealthRead(status="ok", version=version)
```

- [ ] **Step 6: Реализовать `main.py`**

`backend/src/grocery/main.py`:

```python
"""Сборка приложения: create_app() и lifespan (ADR-0014).

Запуск: uvicorn grocery.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grocery.api.routers import health
from grocery.config import get_settings
from grocery.db.session import configure_engine, dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Неполная конфигурация роняет приложение здесь, при старте (ADR-0006).
    settings = get_settings()
    configure_engine(str(settings.db.url))
    try:
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="GroceryList", version=get_settings().app.version, lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    return app
```

- [ ] **Step 7: Запустить тесты — убедиться, что проходят**

Run: `scripts/test.sh tests/api -q`
Expected: `5 passed`.

- [ ] **Step 8: Проверить запуск вживую**

```bash
docker run -d --rm --name grocery-dev -e POSTGRES_PASSWORD=x -p 127.0.0.1:55432:5432 postgres:18-alpine
sleep 3
cd backend
export DB_URL=postgresql+asyncpg://postgres:x@127.0.0.1:55432/postgres APP_PUBLIC_URL=http://localhost:8000
uv run alembic upgrade head
uv run uvicorn grocery.main:create_app --factory --port 8000 &
sleep 2
curl -s localhost:8000/api/health    # {"status":"ok","version":"dev"}
docker stop grocery-dev; sleep 1
curl -s -w ' %{http_code}\n' localhost:8000/api/health    # {"status":"unavailable","version":"dev"} 503
kill %1; cd ..
```

Expected: как в комментариях.

- [ ] **Step 9: Полная проверка и commit**

Run: `scripts/check.sh`
Expected: зелёный.

```bash
git add backend/src/grocery backend/tests
git commit -m "Add FastAPI app factory, unit of work dependency and health endpoint"
```

---

### Task 7: Локальный Postgres, README и CI

**Files:**
- Create: `docker-compose.yml`, `README.md`, `.github/workflows/ci.yml`
- Test: `backend/tests/unit/test_compose.py`

**Interfaces:**
- Consumes: `tests/support.py: POSTGRES_IMAGE, REPO_ROOT`; `scripts/check.sh`
- Produces: `docker compose up -d postgres` для разработки; workflow `CI` (job `check`) на каждый push и pull request. План 5 дополнит `docker-compose.yml` сервисами `caddy`, `backend`, `backup`.

- [ ] **Step 1: Написать падающий тест единого тега Postgres**

`backend/tests/unit/test_compose.py`:

```python
"""docker-compose.yml и тесты используют один образ Postgres (ADR-0011)."""

import re

from tests.support import POSTGRES_IMAGE, REPO_ROOT


def test_compose_postgres_image_matches_tests() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    images = re.findall(r"^\s*image:\s*(postgres:\S+)\s*$", compose, flags=re.MULTILINE)

    assert images == [POSTGRES_IMAGE]
```

Run: `scripts/test.sh unit -k compose`
Expected: FAIL — `FileNotFoundError: .../docker-compose.yml`.

- [ ] **Step 2: Создать `docker-compose.yml`**

`docker-compose.yml`:

```yaml
# Локальная разработка: пока только Postgres. Сервисы caddy, backend и backup
# добавляются в плане деплоя (ADR-0015).
services:
  postgres:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-grocery}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-grocery}
      POSTGRES_DB: ${POSTGRES_DB:-grocery}
    ports:
      # Только localhost: наружу Postgres не публикуется (спец. §9).
      - "127.0.0.1:5432:5432"
    volumes:
      # Postgres 18 хранит данные в подкаталоге версии внутри /var/lib/postgresql.
      - postgres-data:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER:-grocery}"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  postgres-data:
```

Run: `scripts/test.sh unit -k compose`
Expected: `1 passed`.

Run: `docker compose config --quiet && echo ok`
Expected: `ok`.

- [ ] **Step 3: Написать README**

`README.md`:

````markdown
# GroceryList

PWA-список покупок с MCP-сервером: ассистент (Claude, ChatGPT, Codex) добавляет ингредиенты,
приложение обновляется вживую и присылает push.

- Что делает система — [спецификация](docs/superpowers/specs/2026-09-29-grocery-list-design.md)
- Как устроен код — [ADR](docs/adr/README.md)
- План работ — [docs/superpowers/plans](docs/superpowers/plans/README.md)

## Разработка

Нужны [uv](https://docs.astral.sh/uv/) ≥ 0.12 и Docker.

```bash
cp .env.example .env
docker compose up -d postgres
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn grocery.main:create_app --factory --reload
```

Проверка: `curl localhost:8000/api/health` → `{"status":"ok","version":"dev"}`.

Хуки перед коммитом (один раз): `cd backend && uv run pre-commit install`.

## Проверки

Все команды — в `scripts/`, Makefile их только вызывает (ADR-0007):

| Команда | Что делает |
|---|---|
| `make fmt` | форматирование и автоисправления ruff |
| `make lint` | ruff, границы слоёв (import-linter), shellcheck |
| `make typecheck` | mypy strict |
| `make test` / `scripts/test.sh unit` | все тесты / только быстрые, без Docker |
| `make check` | всё вместе; код готов, когда она зелёная |

Интеграционные тесты сами поднимают Postgres в Docker (testcontainers).
````

- [ ] **Step 4: Создать workflow CI**

`.github/workflows/ci.yml`:

```yaml
# Проверки на каждый push и pull request (ADR-0015): те же scripts/check.sh, что локально.
name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Install dependencies
        run: uv sync --project backend --locked
      - name: Check
        run: scripts/check.sh
```

- [ ] **Step 5: Полная проверка и commit**

Run: `scripts/check.sh`
Expected: зелёный.

```bash
git add docker-compose.yml README.md .github/workflows/ci.yml backend/tests/unit/test_compose.py
git commit -m "Add local Postgres compose, README and CI workflow"
```

- [ ] **Step 6: Отправить на GitHub и проверить CI — только с согласия владельца**

Спросить владельца репозитория, можно ли выполнить `git push`. После push:

Run: открыть `https://github.com/stamplevskiyd/GroceryList/actions` (или `gh run watch`, если установлен `gh`)
Expected: job `check` зелёный. Если testcontainers на раннере не видит Docker — проверить, что job идёт на `ubuntu-latest` (там Docker есть по умолчанию).
