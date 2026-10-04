#!/usr/bin/env bash
# Invoked over SSH by deploy.sh, or by tests with fake Docker/curl binaries.
set -euo pipefail
root=${1:?Deployment directory required}
tag=${2:?Image tag required}
commit=${3:?Full commit SHA required}
release=${4:?Release directory required}
# shellcheck source=scripts/release_lib.sh
source "$(dirname "$0")/release_lib.sh"
validate_image_tag "$tag"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 2; }
[[ -f "$root/.env" ]] || { echo 'Prepare the VPS .env first' >&2; exit 2; }
command -v flock >/dev/null
command -v python3 >/dev/null
umask 077
exec 9>"$root/.deploy.lock"
flock -n 9 || { echo 'Another deployment is in progress' >&2; exit 1; }
previous=none
if [[ -f "$root/last-successful/deploy.env" ]]; then
    previous=$(sed -n 's/^IMAGE_TAG=//p' "$root/last-successful/deploy.env")
fi
finish() {
    status=$?
    if ((status != 0)); then
        echo "Deployment failed. Previous successful tag: $previous" >&2
        echo 'No automatic rollback: check migrations before deploying the previous tag.' >&2
        if [[ "$previous" != none ]]; then
            echo "After schema review, run locally: scripts/deploy.sh $previous" >&2
        fi
    fi
}
trap finish EXIT
ln -s "$root/.env" "$release/.env"
printf 'IMAGE_TAG=%s\n' "$tag" > "$release/deploy.env"
compose() {
    IMAGE_TAG="$tag" docker compose --project-name grocerylist --project-directory "$release" \
        --env-file "$root/.env" --env-file "$release/deploy.env" \
        -f "$release/docker-compose.yml" --profile runtime "$@"
}
# Do not print expanded config: it contains database credentials.
config=$(compose config --format json)
public_url=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["caddy"]["environment"]["APP_PUBLIC_URL"])' <<< "$config")
[[ "$public_url" == https://* ]] || { echo 'Production requires an HTTPS APP_PUBLIC_URL' >&2; exit 2; }
compose pull
for service in backend caddy; do
    image=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service" <<< "$config")
    # Both images must match the selected git revision and version before any migration.
    docker image inspect "$image" | python3 -c '
import json, sys
labels = json.load(sys.stdin)[0]["Config"].get("Labels") or {}
if labels.get("org.opencontainers.image.revision") != sys.argv[1] or labels.get("org.opencontainers.image.version") != sys.argv[2]:
    sys.exit("Image revision/version mismatch")
' "$commit" "$tag"
done
compose up -d --no-build --wait --wait-timeout 120 postgres
# A failed dump stops here, before backend startup applies migrations.
compose run --rm --no-deps -T backup "pre-deploy-${tag//./_}"
ln -sfn "$release" "$root/current"
compose up -d --no-build --wait --wait-timeout 180
healthy=false
for _ in {1..30}; do
    if curl --fail --silent --show-error --max-time 10 "${public_url%/}/api/health" |
        python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(d.get("status") != "ok" or d.get("version") != sys.argv[1])' "$tag"; then
        healthy=true
        break
    fi
    sleep 2
done
[[ "$healthy" == true ]] || { echo 'Public health/version check failed' >&2; exit 1; }
ln -sfn "$release" "$root/last-successful"
# Only dangling images, never tagged rollback images or volumes.
docker image prune --force --filter until=24h || echo 'Deployment succeeded, but image cleanup failed' >&2
printf 'Deployed %s (%s) at %s\n' "$tag" "$commit" "$public_url"
