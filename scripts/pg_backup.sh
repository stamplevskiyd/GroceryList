#!/bin/sh
# Запускается в postgres:18-alpine; пароль передаётся только через PGPASSWORD.
set -eu
umask 077
backup_dir=${BACKUP_DIR:-/backups}
keep=${BACKUP_KEEP:-7}
interval=${BACKUP_INTERVAL_SECONDS:-86400}
label=${1:-scheduled}
case "$keep" in ''|*[!0-9]*|0) echo 'BACKUP_KEEP must be positive' >&2; exit 2;; esac
case "$interval" in ''|*[!0-9]*|0) echo 'BACKUP_INTERVAL_SECONDS must be positive' >&2; exit 2;; esac
if [ "$label" = --loop ]; then
    trap 'exit 0' INT TERM
    while :; do
        # Неудачный dump виден в логах; следующая попытка — в следующем цикле.
        "$0" scheduled || echo 'Backup failed' >&2
        sleep "$interval" &
        wait "$!"
    done
fi
case "$label" in ''|*[!A-Za-z0-9_-]*) echo 'Invalid backup label' >&2; exit 2;; esac
mkdir -p "$backup_dir"
lock="$backup_dir/.backup-lock"
if ! mkdir "$lock"; then echo 'Another backup is running (or stale lock exists)' >&2; exit 1; fi
tmp=''
cleanup() {
    if [ -n "$tmp" ]; then rm -f "$tmp"; fi
    rmdir "$lock"
}
trap cleanup 0
trap 'exit 1' INT TERM
tmp=$(mktemp "$backup_dir/.partial.$(date -u +%Y%m%dT%H%M%SZ)-$label.XXXXXX")
name=${tmp##*/}
name=${name#.partial.}.dump
pg_dump --format=custom --no-owner --no-acl --file="$tmp"
# Только завершённый архив участвует в retention и доступен для восстановления.
pg_restore --list "$tmp" >/dev/null
mv "$tmp" "$backup_dir/$name"
tmp=''
count=0
# Имена создаются этим скриптом; сортировка mtime сохраняет последние N даже при
# нескольких бэкапах за секунду и разных label. Не используем лексический порядок.
# shellcheck disable=SC2012
ls -1t -- "$backup_dir"/*.dump | while IFS= read -r file; do
    count=$((count + 1))
    if [ "$count" -gt "$keep" ]; then rm -f "$file"; fi
done
printf '%s\n' "$backup_dir/$name"
