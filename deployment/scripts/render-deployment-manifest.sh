#!/usr/bin/env bash
set -euo pipefail

output_path="${1:-deployment/manifest.yml}"

: "${ENVIRONMENT:?ENVIRONMENT is required}"
: "${SOURCE_SHA:?SOURCE_SHA is required}"
: "${IMAGE_REF:?IMAGE_REF is required}"
: "${PROMPT_VERSION:?PROMPT_VERSION is required}"
: "${CLASSIFIER_RULES_VERSION:?CLASSIFIER_RULES_VERSION is required}"

short_sha="${SOURCE_SHA:0:7}"
deployed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
previous_release="${PREVIOUS_RELEASE:-unknown}"
eval_artifact="${EVAL_ARTIFACT:-unknown}"
dashboard_url="${DASHBOARD_URL:-unknown}"
runbook_url="${RUNBOOK_URL:-docs/incident-response.md}"
rollback_command="workflow_dispatch rollback environment=${ENVIRONMENT} target_sha=${previous_release}"

mkdir -p "$(dirname "$output_path")"

cat > "$output_path" <<EOF
apiVersion: v1
kind: deployment
metadata:
  name: agent-api
  environment: ${ENVIRONMENT}
  commit_sha: ${SOURCE_SHA}
  short_sha: ${short_sha}
  image_ref: ${IMAGE_REF}
  deployed_by: ${GITHUB_ACTOR:-unknown}
  deployed_at: ${deployed_at}
  workflow_run_id: ${GITHUB_RUN_ID:-unknown}
  workflow_run_number: ${GITHUB_RUN_NUMBER:-unknown}
  source_branch: ${GITHUB_REF_NAME:-unknown}
  eval_artifact: ${eval_artifact}
  dashboard_url: ${dashboard_url}
  runbook_url: ${runbook_url}
  rollback_command: ${rollback_command}
spec:
  replicas: 2
  prompt_version: ${PROMPT_VERSION}
  classifier_rules_version: ${CLASSIFIER_RULES_VERSION}
  health:
    live: /livez
    ready: /readyz
  container:
    name: agent-api
    image: ${IMAGE_REF}
    port: 8080
EOF
