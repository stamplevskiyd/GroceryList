#!/usr/bin/env bash
# Изолированная проверка образа, миграций и backup/restore. Пользовательская БД не используется.
set -euo pipefail
cd "$(dirname "$0")/.."
image=${1:-grocerylist-backend:stage5-check}
name="grocery-runtime-check-$$"
cleanup() {
    docker rm -f "$name-backend" "$name-db" >/dev/null 2>&1 || true
    docker volume rm "$name-backups" >/dev/null 2>&1 || true
    docker network rm "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$name" >/dev/null
docker volume create "$name-backups" >/dev/null
docker run -d --name "$name-db" --network "$name" --network-alias postgres \
    -e POSTGRES_PASSWORD=smoke -e POSTGRES_DB=grocery \
    -v "$name-backups:/backups" postgres:18-alpine >/dev/null
ready=false
for _ in {1..60}; do
    if docker exec "$name-db" pg_isready -U postgres -d grocery >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
if [ "$ready" != true ]; then docker logs "$name-db"; exit 1; fi
docker run -d --name "$name-backend" --network "$name" \
    -e APP_PUBLIC_URL=http://localhost:8000 \
    -e DB_URL=postgresql+asyncpg://postgres:smoke@postgres:5432/grocery "$image" >/dev/null
ready=false
for _ in {1..60}; do
    if docker exec "$name-backend" python -c \
        'import json,os,urllib.request; data=json.load(urllib.request.urlopen("http://localhost:8000/api/health",timeout=2)); assert data == {"status":"ok","version":os.environ["APP_VERSION"]}' >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
if [ "$ready" != true ]; then docker logs "$name-backend"; exit 1; fi
# Миграции находятся в установленном пакете; повторный запуск безопасен.
docker exec "$name-backend" alembic upgrade head
docker exec "$name-db" psql -U postgres -d grocery -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE runtime_probe (value text); INSERT INTO runtime_probe VALUES ('Молоко');" >/dev/null
backup() {
    docker run --rm --network "$name" -v "$name-backups:/backups" \
        -v "$PWD/scripts/pg_backup.sh:/scripts/pg_backup.sh:ro" \
        -e PGHOST=postgres -e PGUSER=postgres -e PGPASSWORD=smoke \
        -e PGDATABASE="$1" -e BACKUP_KEEP=1 \
        --entrypoint /bin/sh postgres:18-alpine /scripts/pg_backup.sh smoke
}
backup grocery >/dev/null
backup grocery >/dev/null
# Неуспешный dump не заменяет завершённую копию и не оставляет partial/lock.
if backup nonexistent >/dev/null 2>&1; then echo 'Invalid database backup unexpectedly succeeded' >&2; exit 1; fi
docker exec "$name-db" sh -c \
    'test "$(find /backups -name "*.dump" | wc -l)" -eq 1; test ! -d /backups/.backup-lock; test "$(find /backups -name ".partial.*" | wc -l)" -eq 0'
docker exec "$name-db" createdb -U postgres restored
docker exec "$name-db" sh -c \
    'pg_restore -U postgres --exit-on-error --single-transaction --no-owner --no-acl -d restored /backups/*.dump'
value=$(docker exec "$name-db" psql -U postgres -d restored -Atc 'SELECT value FROM runtime_probe')
test "$value" = 'Молоко'
original=$(docker exec "$name-db" psql -U postgres -d grocery -Atc 'SELECT version_num FROM alembic_version')
restored=$(docker exec "$name-db" psql -U postgres -d restored -Atc 'SELECT version_num FROM alembic_version')
test "$original" = "$restored"
# Ошибка миграций должна завершить контейнер, не запуская API.
if docker run --rm --network "$name" -e APP_PUBLIC_URL=http://localhost:8000 \
    -e DB_URL=postgresql+asyncpg://postgres:smoke@postgres:5432/nonexistent "$image" >/dev/null 2>&1; then
    echo 'Backend unexpectedly started after migration failure' >&2; exit 1
fi
printf 'Runtime, migrations, backup retention/failure and restore: OK\n'
