#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST is required}"
: "${DEPLOY_USER:?DEPLOY_USER is required}"
: "${DEPLOY_SSH_KEY:?DEPLOY_SSH_KEY is required}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${ENVIRONMENT:?ENVIRONMENT is required}"
: "${IMAGE_REF:?IMAGE_REF is required}"
: "${PROMPT_VERSION:?PROMPT_VERSION is required}"
: "${CLASSIFIER_RULES_VERSION:?CLASSIFIER_RULES_VERSION is required}"
: "${GRAFANA_ADMIN_USER:?GRAFANA_ADMIN_USER is required}"
: "${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD is required}"

deploy_port="${DEPLOY_PORT:-22}"
public_port="${PUBLIC_PORT:-8080}"
release_id="${RELEASE_ID:-${GITHUB_SHA:-$(date -u +%Y%m%d%H%M%S)}}"
release_dir="${DEPLOY_PATH}/releases/${release_id}"
ssh_target="${DEPLOY_USER}@${DEPLOY_HOST}"
ssh_key_file="$(mktemp)"
bundle_file="$(mktemp).tgz"
env_file="$(mktemp)"
registry_user_file="$(mktemp)"
registry_token_file="$(mktemp)"

cleanup() {
  rm -f "$ssh_key_file" "$bundle_file" "$env_file" "$registry_user_file" "$registry_token_file"
}
trap cleanup EXIT

printf '%s\n' "$DEPLOY_SSH_KEY" > "$ssh_key_file"
chmod 600 "$ssh_key_file"

tar -czf "$bundle_file" \
  compose.prod.yml \
  deployment/nginx.conf \
  prometheus/prometheus.prod.yml \
  prometheus/alert-rules.yml \
  alertmanager/alertmanager.yml \
  grafana/provisioning \
  grafana/dashboards

ssh -i "$ssh_key_file" -p "$deploy_port" -o StrictHostKeyChecking=accept-new "$ssh_target" \
  "mkdir -p '$release_dir'"
scp -i "$ssh_key_file" -P "$deploy_port" "$bundle_file" "$ssh_target:$release_dir/release.tgz"

cat > "$env_file" <<EOF
AGENT_API_IMAGE=${IMAGE_REF}
PROMPT_VERSION=${PROMPT_VERSION}
CLASSIFIER_RULES_VERSION=${CLASSIFIER_RULES_VERSION}
LOG_LEVEL=${LOG_LEVEL:-INFO}
LOG_RAW_PROMPTS=${LOG_RAW_PROMPTS:-false}
PUBLIC_PORT=${public_port}
PROMETHEUS_PORT=${PROMETHEUS_PORT:-9090}
ALERTMANAGER_PORT=${ALERTMANAGER_PORT:-9093}
GRAFANA_PORT=${GRAFANA_PORT:-3000}
GRAFANA_ADMIN_USER=${GRAFANA_ADMIN_USER}
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
PROMETHEUS_RETENTION=${PROMETHEUS_RETENTION:-15d}
EOF

scp -i "$ssh_key_file" -P "$deploy_port" "$env_file" "$ssh_target:$release_dir/.env"

if [[ -n "${GHCR_READ_TOKEN:-}" && -n "${GHCR_READ_USERNAME:-}" ]]; then
  printf '%s' "$GHCR_READ_USERNAME" > "$registry_user_file"
  printf '%s' "$GHCR_READ_TOKEN" > "$registry_token_file"
  scp -i "$ssh_key_file" -P "$deploy_port" "$registry_user_file" "$ssh_target:$release_dir/.registry-username"
  scp -i "$ssh_key_file" -P "$deploy_port" "$registry_token_file" "$ssh_target:$release_dir/.registry-token"
fi

ssh -i "$ssh_key_file" -p "$deploy_port" "$ssh_target" bash -s -- "$DEPLOY_PATH" "$release_dir" "$public_port" <<'REMOTE'
set -euo pipefail

deploy_path="$1"
release_dir="$2"
public_port="$3"

cd "$release_dir"
tar -xzf release.tgz

previous=""
if [[ -L "$deploy_path/current" ]]; then
  previous="$(readlink -f "$deploy_path/current")"
  ln -sfn "$previous" "$deploy_path/previous"
fi

if [[ -f .registry-token && -f .registry-username ]]; then
  docker login ghcr.io -u "$(cat .registry-username)" --password-stdin < .registry-token
  rm -f .registry-token .registry-username
fi

ln -sfn "$release_dir" "$deploy_path/current"
cd "$deploy_path/current"

set +e
docker compose -f compose.prod.yml pull
pull_status=$?
docker compose -f compose.prod.yml up -d --remove-orphans
up_status=$?
curl --fail --retry 12 --retry-all-errors --retry-delay 5 "http://localhost:${public_port}/readyz"
ready_status=$?
curl --fail --retry 6 --retry-all-errors --retry-delay 5 "http://localhost:${public_port}/metrics" >/dev/null
metrics_status=$?
set -e

if [[ "$pull_status" -ne 0 || "$up_status" -ne 0 || "$ready_status" -ne 0 || "$metrics_status" -ne 0 ]]; then
  echo "Deployment failed; attempting rollback to previous release." >&2
  if [[ -n "$previous" && -d "$previous" ]]; then
    ln -sfn "$previous" "$deploy_path/current"
    cd "$deploy_path/current"
    docker compose -f compose.prod.yml up -d --remove-orphans
  fi
  exit 1
fi
REMOTE
