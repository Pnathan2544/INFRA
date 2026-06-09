import json
import re
from pathlib import Path

KNOWN_AGENT_METRICS = {
    'agent_requests_total',
    'agent_rejections_total',
    'agent_request_outcomes_total',
    'agent_invalid_requests_total',
    'agent_request_payload_bytes',
    'agent_request_payload_bytes_bucket',
    'agent_request_payload_bytes_count',
    'agent_request_payload_bytes_sum',
    'agent_message_length_chars',
    'agent_message_length_chars_bucket',
    'agent_message_length_chars_count',
    'agent_message_length_chars_sum',
    'agent_request_latency_seconds',
    'agent_request_latency_seconds_bucket',
    'agent_request_latency_seconds_count',
    'agent_request_latency_seconds_sum',
    'agent_classification_latency_seconds',
    'agent_classification_latency_seconds_bucket',
    'agent_classification_latency_seconds_count',
    'agent_classification_latency_seconds_sum',
    'agent_generation_latency_seconds',
    'agent_generation_latency_seconds_bucket',
    'agent_generation_latency_seconds_count',
    'agent_generation_latency_seconds_sum',
    'agent_prompt_version_info',
    'agent_classifier_rules_version_info',
}


def find_unknown_agent_metrics(expr: str) -> list[str]:
    """Catch dashboard panels that reference agent metrics the app does not emit."""
    tokens = set(re.findall(r'\b[a-zA-Z_:][a-zA-Z0-9_:]*\b', expr))
    return sorted(token for token in tokens if token.startswith('agent_') and token not in KNOWN_AGENT_METRICS)


def validate_dashboard(path: Path) -> None:
    with path.open(encoding='utf-8') as file:
        dashboard = json.load(file)

    required_top_level = ['title', 'uid', 'schemaVersion', 'panels']
    missing = [key for key in required_top_level if key not in dashboard]
    if missing:
        raise ValueError(f'{path}: missing required keys: {", ".join(missing)}')

    panels = dashboard['panels']
    if not isinstance(panels, list) or not panels:
        raise ValueError(f'{path}: dashboard must contain at least one panel')

    panel_ids = set()
    for panel in panels:
        panel_id = panel.get('id')
        title = panel.get('title')
        targets = panel.get('targets', [])

        if panel_id in panel_ids:
            raise ValueError(f'{path}: duplicate panel id {panel_id}')
        panel_ids.add(panel_id)

        if not title:
            raise ValueError(f'{path}: panel {panel_id} is missing a title')

        for target in targets:
            expr = target.get('expr')
            if expr is not None and ('TODO' in expr or expr.strip() == 'vector(0)'):
                raise ValueError(f'{path}: panel {panel_id} has placeholder query {expr!r}')
            if expr is not None:
                unknown_metrics = find_unknown_agent_metrics(expr)
                if unknown_metrics:
                    raise ValueError(
                        f'{path}: panel {panel_id} references unknown agent metrics: ' f'{", ".join(unknown_metrics)}'
                    )


def main() -> None:
    dashboard_dir = Path('grafana/dashboards')
    dashboards = sorted(dashboard_dir.glob('*.json'))
    if not dashboards:
        raise SystemExit('No Grafana dashboards found')

    for dashboard in dashboards:
        validate_dashboard(dashboard)
        print(f'Validated {dashboard}')


if __name__ == '__main__':
    main()
