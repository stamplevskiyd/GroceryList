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

- [ ] Caddyfile: HTTPS, маршруты API/MCP/OAuth/discovery, SSE без буферизации, SPA fallback.
- [ ] caddy.Dockerfile: сборка frontend → официальный Caddy. Сейчас frontend содержит
  только контракт; добавить минимальную честную страницу до полноценного PWA этапа 7.
- [ ] Полный Compose, проверка прокси MCP/SSE и локальный HTTPS smoke.

## 3. CI/CD

- [ ] images.yml после успешного CI: main и v*, Docker Hub, SHA и версия, linux/amd64.
- [ ] deploy.sh: SSH с pinned host key, Compose/backup script версии релиза,
  pull, pre-deploy backup, миграции, health с ожидаемой версией, prune.
- [ ] deploy.yml: ручной запуск и релизные теги, production environment, concurrency.
- [ ] Runbook подготовки VPS, backup/restore и отката; lint и проверки workflow.

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
