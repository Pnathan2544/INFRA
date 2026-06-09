# AI-Ops Take-Home Test

A self-contained repository for evaluating DevOps + AIOps skills. This repo simulates an "LLM Agent API" that sometimes refuses requests and emits metrics.

## Quick Start

Prerequisites:

- Python 3.11 for the cleanest match with CI and runtime containers
- Docker with the Compose plugin
- GNU Make

```bash
# Install local developer/test tooling
python -m pip install -r requirements-dev.txt

# Start the full stack (API, Prometheus, Grafana, Traffic Generator)
make up

# View logs
make logs

# Run evaluation suite
make eval

# Stop everything
make down
```

## Local Endpoints

| Service | URL | Credentials |
|---------|-----|-------------|
| Agent API | http://localhost:8080 | - |
| Metrics | http://localhost:8080/metrics | - |
| Prometheus | http://localhost:9090 | - |
| Alertmanager | http://localhost:9093 | - |
| Grafana | http://localhost:3000 | admin/admin |

## Architecture

```
Traffic Generator --> Agent API (8080) --> /metrics
                                         |
                                         v
                                  Prometheus (9090)
                                         |
                                         v
                                    Grafana (3000)
```

## Agent API Endpoints

### POST /ask
Send a message to the agent.

```bash
curl -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather?"}'
```

Response:
```json
{
  "rejected": false,
  "reason": null,
  "prompt_version": "v1.0.0",
  "answer": "I'd be happy to assist with your request."
}
```

### GET /livez, /readyz, /healthz
Liveness, readiness, and compatibility health endpoints.

```bash
curl http://localhost:8080/readyz
```

### GET /metrics
Prometheus metrics endpoint.

```bash
curl http://localhost:8080/metrics
```

## Rejection Logic

The agent rejects requests based on content patterns:

| Reason | Trigger Patterns |
|--------|------------------|
| `prompt_injection` | "ignore instructions", "system prompt", "jailbreak" |
| `secrets_request` | "password", "api key", "credentials" |
| `dangerous_action` | "restart prod", "delete database", "rm -rf" |

## Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `agent_requests_total` | Counter | `prompt_version`, `route` |
| `agent_rejections_total` | Counter | `prompt_version`, `reason` |
| `agent_request_outcomes_total` | Counter | `prompt_version`, `route`, `status_code`, `outcome` |
| `agent_invalid_requests_total` | Counter | `prompt_version`, `route`, `reason` |
| `agent_request_payload_bytes` | Histogram | `route`, `outcome` |
| `agent_message_length_chars` | Histogram | `prompt_version`, `outcome` |
| `agent_request_latency_seconds` | Histogram | `prompt_version`, `route` |
| `agent_classification_latency_seconds` | Histogram | `prompt_version`, `outcome` |
| `agent_generation_latency_seconds` | Histogram | `prompt_version` |
| `agent_prompt_version_info` | Gauge | `prompt_version` |
| `agent_classifier_rules_version_info` | Gauge | `classifier_rules_version` |

## Evaluation Runner

The eval runner tests the agent against two datasets:

- **Golden Dataset**: Normal messages that should be accepted
- **Adversarial Dataset**: Malicious messages that should be rejected

```bash
# Run eval
make eval

# Results are saved to ./eval-results/
```

### Gate Thresholds

| Gate | Threshold | Description |
|------|-----------|-------------|
| `min_golden_accuracy` | 90% | Golden messages should be accepted |
| `max_golden_rejection_rate` | 5% | Don't reject too many legitimate requests |
| `min_adversarial_rejection_rate` | 60% | Must reject most malicious requests |
| `min_reason_accuracy` | 90% | Rejection reasons should match the expected class |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMPT_VERSION` | v1.0.0 | Version string included in responses/metrics |
| `CLASSIFIER_RULES_VERSION` | rules-v1.0.0 | Version string for deterministic classifier rules |
| `LOG_RAW_PROMPTS` | false | Protected debug switch for raw prompt logging |
| `REQUEST_INTERVAL_MS` | 500 | Traffic generator request interval |
| `REJECTION_MIX_RATIO` | 0.15 | Ratio of rejection-triggering traffic |

## Validation

Run the local quality gates before submitting:

```bash
make verify
```

`make verify` runs linting, formatting checks, type checks, unit tests, security
checks, Docker Compose config validation, Prometheus rule validation,
Alertmanager config validation, and Grafana dashboard validation. Docker must be
running for the containerized Prometheus/Alertmanager checks and for the full
stack. Use Python 3.11-3.13 for local security checks; CI uses Python 3.11.

If Docker is not available, the non-container checks can still be run directly:

```bash
make lint
make type
make test
make security
make validate-config
make validate-prod-config
```

## CI/CD and Production Deployment

The CI/CD workflow keeps `quality-gate` as the single required branch-protection
check while splitting implementation into code quality, unit tests, security,
config validation, and integration eval jobs. Pushes to `main` build an immutable
GHCR image tagged by commit SHA and upload deployment metadata artifacts.

Production Docker VM deployment is available when repository/environment
variable `ENABLE_DOCKER_VM_DEPLOY=true` and the staging/production environment
secrets are configured. Deployments promote the same image digest through
staging, canary eval, production approval, and rollback.

The production deployment path is intentionally optional for the take-home
submission. The portable, reviewer-runnable contract is:

1. `make verify` passes.
2. `make up` starts API, Prometheus, Alertmanager, Grafana, and the traffic
   generator.
3. `make eval` passes the behavioral quality gate.
4. `git status --short` shows only intentionally uncommitted local artifacts.

The local Alertmanager config keeps the same routing and receiver names that a
production deployment would use, but it omits outbound notification integrations
so reviewers can run it safely. In production, wire those receiver names to the
team's real paging/ticketing integrations. Alert rules derive their
`environment` label and Grafana base URL from Prometheus `external_labels`, so
the same rule file can run locally and in production.

For production Compose validation without real secrets, use:

```bash
docker compose --env-file deployment/example.env -f compose.prod.yml config
```

## For Candidates

See [CANDIDATE_INSTRUCTIONS.md](./CANDIDATE_INSTRUCTIONS.md) for the take-home test prompt.
