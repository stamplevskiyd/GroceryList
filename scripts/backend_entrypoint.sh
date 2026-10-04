#!/bin/sh
# Один процесс: миграции завершаются до начала приёма HTTP-запросов.
set -eu
APP_VERSION=$(cat /app/VERSION)
export APP_VERSION
alembic upgrade head
exec "$@"
