#!/usr/bin/env bash
# Ship only committed release files. No checkout mutation and no build on the VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/release_lib.sh
source scripts/release_lib.sh
tag=${1:?Usage: scripts/deploy.sh <12-character-SHA|vX.Y.Z>}
validate_image_tag "$tag"
: "${VPS_HOST:?Set VPS_HOST}"
: "${VPS_USER:?Set VPS_USER}"
: "${VPS_KNOWN_HOSTS:?Set VPS_KNOWN_HOSTS to the verified SSH host key}"
deploy_dir=${VPS_DEPLOY_DIR:-/opt/grocerylist}
if [[ ! "$VPS_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ||
      ! "$VPS_USER" =~ ^[a-z_][a-z0-9_-]*$ ||
      ! "$deploy_dir" =~ ^/[A-Za-z0-9_/-]+$ || "$deploy_dir" == / ]]; then
    echo 'Invalid VPS host, user or absolute deployment directory' >&2
    exit 2
fi
if [[ "$tag" == v* ]]; then
    commit=$(git rev-parse --verify "refs/tags/$tag^{commit}")
else
    commit=$(git rev-parse --verify "$tag^{commit}")
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
umask 077
printf '%s\n' "$VPS_KNOWN_HOSTS" > "$tmp/known_hosts"
if [[ -n "${VPS_SSH_KEY_FILE:-}" ]]; then
    key=$VPS_SSH_KEY_FILE
else
    : "${VPS_SSH_KEY:?Set VPS_SSH_KEY or VPS_SSH_KEY_FILE}"
    printf '%s\n' "$VPS_SSH_KEY" > "$tmp/key"
    key=$tmp/key
fi
ssh_opts=(-i "$key" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$tmp/known_hosts" -o GlobalKnownHostsFile=/dev/null
    -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
release="$deploy_dir/releases/$tag-$(date -u +%Y%m%dT%H%M%SZ)-$$"
git archive --format=tar --output="$tmp/release.tar" "$commit" \
    docker-compose.yml scripts/pg_backup.sh scripts/deploy_remote.sh scripts/release_lib.sh
# All interpolated remote values above are restricted to shell-safe characters.
# shellcheck disable=SC2029
ssh "${ssh_opts[@]}" "$VPS_USER@$VPS_HOST" \
    "umask 077; mkdir -p '$release' && tar -xf - -C '$release'" < "$tmp/release.tar"
# shellcheck disable=SC2029
ssh "${ssh_opts[@]}" "$VPS_USER@$VPS_HOST" \
    "bash '$release/scripts/deploy_remote.sh' '$deploy_dir' '$tag' '$commit' '$release'"
