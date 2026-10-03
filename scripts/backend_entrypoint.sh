#!/bin/sh
# Один процесс: миграции завершаются до начала приёма HTTP-запросов.
set -eu
alembic upgrade head
exec "$@"
