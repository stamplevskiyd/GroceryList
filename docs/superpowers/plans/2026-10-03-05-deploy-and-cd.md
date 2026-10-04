# Этап 5 — деплой и CD

Спека: §9–10, §13. Решения: ADR-0006/0007/0013/0014/0015.
Приоритет — локально проверяемая инфраструктура; доступы и первый production deploy отдельно.

## 1. Backend и восстановление БД

- [x] Multi-stage backend.Dockerfile: Python 3.14, locked uv, только runtime dependencies,
  non-editable установленный пакет с миграциями, непривилегированный пользователь.
- [x] Миграции до запуска API, один Uvicorn worker, версия из build-arg.
- [x] Профиль runtime в Compose: backend с healthcheck и backup, отдельный volume копий.
  Для разработки Postgres остаётся доступен отдельно.
- [x] Custom-format pg_dump, атомарная публикация файла, lock, retention N копий,
  ежедневный цикл; ошибка не удаляет последнюю успешную копию.
- [x] Проверить сборку и scripts/check_runtime.sh на изолированной БД: health/version,
  миграции и повторный startup, реальные данные после restore, retention и ошибки.
- [x] Полный scripts/check.sh после инфраструктурных изменений.

## 2. Caddy и статика

- [x] Caddyfile: HTTPS, маршруты API/MCP/OAuth/discovery, SSE без буферизации, SPA fallback.
- [x] caddy.Dockerfile: сборка frontend → официальный Caddy; минимальная стартовая
  страница до полноценного PWA этапа 7.
- [x] Compose: Caddy, постоянные volumes, настройка адреса и портов.
- [ ] Проверка прокси MCP/SSE и локальный HTTPS smoke.

Код Compose и стартовой страницы добавлен. Проверка в локальном браузере обязательна
и выполняется владельцем вручную; ассистент пишет код и запускает штатные проверки,
не управляет браузером и системными сертификатами. До ручной приёмки блок не закрывается.
Страница до этапа 7 явно сообщает, что интерфейс списка ещё готовится.

Проверки кода: `scripts/check.sh` — 473 теста, линтеры, типы, контракт API и сборка Vite
успешны. `docker build -f caddy.Dockerfile -t grocerylist-caddy:stage5-check .` успешен;
в сборке также проверен разбор Caddyfile. 2026-10-04 владелец подтвердил открытие страницы
в Safari на `http://localhost:8080`; health через Caddy также вернул `ok`. Проверки
HTTPS, MCP и SSE через Caddy остаются открытыми.

## 3. CI/CD

- [x] images.yml после успешного CI: main и v*, Docker Hub, SHA и версия, linux/amd64.
- [x] deploy.sh: SSH с pinned host key, Compose/backup script версии релиза,
  pull, pre-deploy backup, миграции, health с ожидаемой версией, prune.
- [x] deploy.yml: ручной запуск и релизные теги, production environment, concurrency.
- [x] Runbook подготовки VPS, backup/restore и отката; lint и проверки workflow.

Код CI/CD готов; workflow-файлы связываются через `needs`/`workflow_call`. Инструкция —
[`../../deployment.md`](../../deployment.md). `scripts/check.sh` прошёл: 492 теста,
включая 19 сценариев деплоя с подставными командами, ShellCheck, actionlint, типы и сборку.
Новый backend-образ прошёл `scripts/check_runtime.sh`: версия не подменяется runtime
переменной, миграции и backup/restore работают. Настоящие workflows, публикация образов
в Docker Hub и SSH-деплой ещё не запускались; они входят во внешнюю приёмку.

## 4. Внешняя приёмка

- [ ] Доступ к VPS, GitHub/Docker Hub secrets; первый deploy.
- [ ] HTTPS и Cloudflare: SSE, MCP handshake, metadata и отсутствие обрывов.
- [ ] Подключение Claude Code по PAT владельца.

Этап считается выполненным после внешней приёмки. Самостоятельная подготовка инфраструктуры
не означает успешного production deploy.

## Результат первого блока — 2026-10-03

Образ собран локально. `scripts/check_runtime.sh` прошёл на временных Docker-ресурсах:
health с версией сборки, upgrade до 0005 и повторный upgrade, restore текста «Молоко»
и alembic_version в новую БД, retention одной копии, cleanup после ошибки dump,
завершение backend при ошибке миграции. Отдельно проверен Compose-профиль runtime:
все сервисы стартуют, backend healthy, версия совпадает с IMAGE_TAG, ручной backup работает.
Временные контейнеры, сети и volumes удалены. Полный scripts/check.sh зелёный:
473 теста за 25.69 с. Следующая задача — Caddy и статика, затем CI/CD.

## Первичные источники

- [uv в Docker](https://docs.astral.sh/uv/guides/integration/docker/) — locked sync,
  промежуточные слои и non-editable установка.
- [pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html),
  [pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html) — custom archives
  и восстановление с проверкой ошибок в одной транзакции.
