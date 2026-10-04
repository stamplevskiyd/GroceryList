# Деплой GroceryList

2026-10-04 образы `v0.1.1` опубликованы в Docker Hub и запущены на VPS
`94.159.101.162` в `/opt/grocerylist`. Backend и Postgres healthy, локальный
`/api/health` возвращает `{"status":"ok","version":"v0.1.1"}`, ежедневный backup создан.
Ручной архив также успешно восстановлен в отдельную временную БД: схема `0005`,
пользователей пока нет. Тестовая БД после проверки удалена.

**Внешний деплой пока не принят:** `https://s157254.love-is.nexus` через Cloudflare
отвечает `302 Location: https://h2.nexus`, а не приложением. ACME-проверка не достигает
нашего Caddy, поэтому публичный сертификат не выпущен. Требуется направить домен
на этот VPS и убрать внешнее перенаправление. После исправления повторить failed job
в [релизном workflow](https://github.com/stamplevskiyd/GroceryList/actions/runs/37192486668).
`last-successful` ещё не установлен; HTTPS, внешний вход, MCP и SSE не подтверждены.

Локальную страницу владелец ранее проверил в Safari; это не проверка HTTPS, MCP и SSE на VPS.

## Подготовка VPS

1. Установить Docker Engine с Compose plugin, `bash`, `curl`, `python3` и `flock`
   (пакет `util-linux`). Compose должен поддерживать `up --wait --wait-timeout`.
2. Создать пользователя `deploy`, разрешить ему Docker и вход по SSH-ключу. Создать
   `/opt/grocerylist`, владельцем назначить `deploy`. Порт SSH — 22.
3. Открыть входящие 22, 80 и 443. Направить домен на VPS либо настроить прокси хостинга.
4. В `/opt/grocerylist/.env` перенести `.env.example`, выставить права `600`.
   Задать уникальный пароль Postgres, обновить `DB_URL` и `CONTAINER_DB_URL`
   (пароль в URL кодируется), указать нужный Docker Hub namespace в `DOCKERHUB_USER`.
5. Для Caddy задать:

   ```dotenv
   APP_PUBLIC_URL=https://ваш-домен
   CADDY_BIND=0.0.0.0
   CADDY_HTTP_PORT=80
   CADDY_HTTPS_PORT=443
   ```

   `IMAGE_TAG` устанавливает скрипт отдельно в `deploy.env`; `APP_VERSION` внутри backend
   берётся из файла, зашитого в образ при сборке, а не из `.env`.

Секреты приложения остаются на VPS. Скрипт не копирует локальную `.env` и не создаёт
системное доверие к сертификатам. Публичный HTTPS обслуживает Caddy.

## GitHub и Docker Hub

Создать публичные Docker Hub repositories `grocerylist-backend`, `grocerylist-caddy`.
Repository secrets GitHub:

- `DOCKERHUB_USERNAME` — тот же namespace, что в `.env` VPS;
- `DOCKERHUB_TOKEN` — токен с правом push только нужных образов.

Создать GitHub environment **production**. Его secrets:

- `VPS_HOST` — имя хоста или IPv4 без протокола;
- `VPS_USER` — `deploy`;
- `VPS_SSH_KEY` — закрытый SSH-ключ этого пользователя;
- `VPS_KNOWN_HOSTS` — запись known_hosts с заранее проверенным ключом сервера.

Проверить fingerprint ключа через доверенный канал, например консоль VPS. Один только
`ssh-keyscan` без сверки не подтверждает подлинность сервера. Host key проверяется строго,
общесистемный known_hosts не используется. Для смены каталога есть environment variable
GitHub `VPS_DEPLOY_DIR` (по умолчанию `/opt/grocerylist`).

Ограничить deployment branches/tags environment `production` доверенными `main` и `v*`,
настроить защиту релизных тегов и обязательный CI для `main`. В workflow нет автоматического
пуша git-тегов: публикация тега — действие владельца.

## Как выпускается версия

`ci.yml` проверяет каждый push и PR. После успешного job `check` вызывает reusable
`images.yml` только для push в `main` и тегов `v*`. PR не получает Docker Hub credentials.
Собираются оба образа для `linux/amd64` с тегом из первых **12 символов SHA**.

Для релиза `v0.1.0` дополнительно собираются образы с этим тегом. У backend это отдельный
слой с `APP_VERSION=v0.1.0`; SHA-образ сохраняет свою SHA-версию. Поэтому `/api/health`
соответствует выбранному тегу и при ручном деплое SHA, и при деплое версии. Метки OCI
обоих образов содержат полный git SHA и тег версии. `latest` не используется.

Push в `main` не деплоит. После успешной сборки обоих релизных образов CI вызывает
`deploy.yml`. Вручную: Actions → Deploy → Run workflow, поле `tag` — 12-символьный SHA
или релиз `v0.1.0` / `v0.1.0-rc.1`. Соответствующие образы уже должны быть опубликованы.
Сборка с ноутбука на VPS не выполняется.

Вызов `deploy.yml` использует `secrets: inherit`: без него при первом релизе
environment secrets приходили пустыми ([actions/runner#4453](https://github.com/actions/runner/issues/4453)).
Секреты VPS хранятся в `production`, а ключ для деплоя отдельный от личного SSH-ключа.

Ручной запуск того же скрипта с ноутбука (git refs должны быть актуальны):

```bash
export VPS_HOST=server.example
export VPS_USER=deploy
export VPS_SSH_KEY_FILE="$HOME/.ssh/grocery_deploy"
export VPS_KNOWN_HOSTS="$(cat /путь/к/проверенному/known_hosts)"
scripts/deploy.sh v0.1.0
```

Берутся **закоммиченные** Compose и скрипты выбранной версии через `git archive`.
Текущие незакоммиченные изменения не отправляются. Версию без файлов CI/CD этим способом
развернуть нельзя. SSH использует закреплённый host key и отдельный закрытый ключ.

## Что делает деплой

1. Передаёт конфигурацию в отдельный `/opt/grocerylist/releases/<tag>-<time>-<pid>`.
2. Захватывает серверный `flock`; параллельные деплои также запрещены в GitHub Actions.
3. Подключает серверную `.env`, создаёт release-specific `deploy.env`, скачивает образы.
4. Сверяет OCI revision/version обоих образов с выбранным коммитом и тегом.
5. Дожидается Postgres и делает `pre-deploy` backup. Ошибка dump останавливает деплой
   **до запуска новых миграций**. При первом запуске копия содержит ещё пустую БД.
6. Переключает `current` на выбранную конфигурацию, запускает runtime без сборки.
   Backend применяет миграции до старта API.
7. Проверяет **публичный HTTPS** `/api/health`: `status=ok`, `version=<tag>`.
   Локального health контейнера недостаточно.
8. Только после успеха обновляет `last-successful`, удаляет dangling images старше суток.
   Тегированные образы для отката и Docker volumes не удаляются. Ошибка очистки выводит
   предупреждение и не превращает уже проверенный успешный деплой в неуспешный.

Имя Compose-проекта всегда `grocerylist`: новые каталоги релизов используют те же volumes.
`current` — последняя попытка запуска, `last-successful` — последняя подтверждённая версия.
Ошибка не вызывает автоматический откат миграций и не меняет `last-successful`.

Операторские команды на VPS:

```bash
cd /opt/grocerylist/current
dc() { docker compose -p grocerylist --env-file .env --env-file deploy.env --profile runtime "$@"; }
dc ps
dc logs --tail 100 backend caddy backup
dc exec backend python -m grocery create-user anna
dc run --rm backup manual
```

## Бэкапы и откат

Custom-format dump записывается в `postgres-backups` атомарно. Ежедневные и pre-deploy
копии используют **общий** лимит `BACKUP_KEEP`; частые деплои вытесняют более старые копии.
Настроить копирование архивов за пределы VPS и периодически проверять восстановление.
Оставшиеся каталоги релизов и тегированные образы удалять вручную после выбора окна отката.

При ошибке деплой выводит предыдущий успешный тег. Сначала проверить логи и версию схемы:

```bash
dc logs --tail 100 backend
dc exec backend alembic current
```

Если миграции не применились либо схема совместима со старой версией, повторно запустить
Deploy с предыдущим тегом. Если схема несовместима, остановить запись (`dc stop backend`),
затем выполнить подходящий `alembic downgrade <revision>` текущим образом либо восстановить
pre-deploy dump в **отдельную новую БД**. Не подменять схему работающему backend.

```bash
dc exec postgres sh -c 'createdb -U "$POSTGRES_USER" grocery_restored'
dc run --rm --entrypoint pg_restore backup \
  --exit-on-error --single-transaction --no-owner --no-acl \
  --dbname=grocery_restored /backups/ИМЯ_АРХИВА.dump
```

Проверить данные, изменить `CONTAINER_DB_URL` и `POSTGRES_DB` в серверной `.env` на новую БД,
чтобы и приложение, и последующие бэкапы использовали её, затем развернуть предыдущий тег.
Старую БД сохранить до подтверждения восстановления. Восстановление снимка теряет изменения,
сделанные после него; решение принимает оператор. Удаление volume не является откатом.

## Приёмка владельцем

- В браузере открыть сайт по HTTPS, войти, проверить `/api/me` и работу со списком через Swagger.
- Проверить, что ошибочные `/api/*` возвращают API-ошибку, а не HTML страницы.
- Подключить Claude Code по PAT; проверить MCP handshake и реальное изменение списка.
- Проверить SSE через Cloudflare и появление изменения от другого клиента.
- Выполнить восстановление тестового dump в отдельную БД.

Проверки кода (`scripts/check.sh`, actionlint, тесты сценариев деплоя с подставными командами)
не заменяют первый реальный запуск workflows, внешний деплой и ручную приёмку.
