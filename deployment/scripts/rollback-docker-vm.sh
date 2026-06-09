#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST is required}"
: "${DEPLOY_USER:?DEPLOY_USER is required}"
: "${DEPLOY_SSH_KEY:?DEPLOY_SSH_KEY is required}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"

deploy_port="${DEPLOY_PORT:-22}"
public_port="${PUBLIC_PORT:-8080}"
target_sha="${TARGET_SHA:-}"
ssh_target="${DEPLOY_USER}@${DEPLOY_HOST}"
ssh_key_file="$(mktemp)"

cleanup() {
  rm -f "$ssh_key_file"
}
trap cleanup EXIT

printf '%s\n' "$DEPLOY_SSH_KEY" > "$ssh_key_file"
chmod 600 "$ssh_key_file"

ssh -i "$ssh_key_file" -p "$deploy_port" "$ssh_target" bash -s -- "$DEPLOY_PATH" "$public_port" "$target_sha" <<'REMOTE'
set -euo pipefail

deploy_path="$1"
public_port="$2"
target_sha="$3"

if [[ -n "$target_sha" ]]; then
  target="$deploy_path/releases/$target_sha"
else
  target="$(readlink -f "$deploy_path/previous")"
fi

if [[ ! -d "$target" ]]; then
  echo "Rollback target does not exist: $target" >&2
  exit 1
fi

if [[ -L "$deploy_path/current" ]]; then
  ln -sfn "$(readlink -f "$deploy_path/current")" "$deploy_path/previous"
fi

ln -sfn "$target" "$deploy_path/current"
cd "$deploy_path/current"
docker compose -f compose.prod.yml up -d --remove-orphans
curl --fail --retry 12 --retry-all-errors --retry-delay 5 "http://localhost:${public_port}/readyz"
curl --fail --retry 6 --retry-all-errors --retry-delay 5 "http://localhost:${public_port}/metrics" >/dev/null
REMOTE
