import json
from pathlib import Path


def iter_panels(panels: list[dict]):
    for panel in panels:
        yield panel
        nested_panels = panel.get("panels")
        if isinstance(nested_panels, list):
            yield from iter_panels(nested_panels)


def validate_dashboard(path: Path) -> None:
    with path.open(encoding="utf-8") as file:
        dashboard = json.load(file)

    required_top_level = ["title", "uid", "schemaVersion", "panels"]
    missing = [key for key in required_top_level if key not in dashboard]
    if missing:
        raise ValueError(f"{path}: missing required keys: {', '.join(missing)}")

    panels = dashboard["panels"]
    if not isinstance(panels, list) or not panels:
        raise ValueError(f"{path}: dashboard must contain at least one panel")

    panel_ids = set()
    for panel in iter_panels(panels):
        panel_id = panel.get("id")
        title = panel.get("title")

        if panel_id in panel_ids:
            raise ValueError(f"{path}: duplicate panel id {panel_id}")
        panel_ids.add(panel_id)

        if not title:
            raise ValueError(f"{path}: panel {panel_id} is missing a title")

        targets = panel.get("targets", [])
        if not isinstance(targets, list):
            raise ValueError(f"{path}: panel {panel_id} targets must be a list")


def main() -> None:
    dashboard_dir = Path("grafana/dashboards")
    dashboards = sorted(dashboard_dir.glob("*.json"))
    if not dashboards:
        raise SystemExit("No Grafana dashboards found")

    for dashboard in dashboards:
        validate_dashboard(dashboard)
        print(f"Validated {dashboard}")


if __name__ == "__main__":
    main()
