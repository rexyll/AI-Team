from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from runtime.dashboard_html import render_dashboard
from runtime.dashboard_api import DashboardQuery, DEFAULT_DASHBOARD_QUERY


def write_dashboard(
    tasks: Iterable[Any],
    output: str | Path,
    *,
    project_id: str | None = None,
    query: DashboardQuery | None = None,
) -> Path:
    """Generate a self-contained dashboard HTML file from the read model."""
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshot = (query or DEFAULT_DASHBOARD_QUERY).snapshot(tasks, project_id=project_id)
    destination.write_text(render_dashboard(snapshot), encoding="utf-8")
    return destination
