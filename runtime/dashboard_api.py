from __future__ import annotations

from typing import Any, Iterable

from runtime.observability_dashboard import DashboardAgentSummary, DashboardSnapshot, DashboardTaskSummary, DashboardWorkflowSummary, ObservabilityDashboard


class DashboardQuery:
    """Stable read-only query facade for CLI/API consumers."""

    def __init__(self, dashboard: ObservabilityDashboard | None = None) -> None:
        self._dashboard = dashboard or ObservabilityDashboard()

    def snapshot(self, tasks: Iterable[Any], *, project_id: str | None = None) -> DashboardSnapshot:
        return self._dashboard.snapshot(tasks, project_id=project_id)

    def workflow(self, tasks: Iterable[Any], *, project_id: str | None = None) -> DashboardWorkflowSummary:
        return self.snapshot(tasks, project_id=project_id).workflow

    def agents(self, tasks: Iterable[Any], *, project_id: str | None = None) -> tuple[DashboardAgentSummary, ...]:
        return self.snapshot(tasks, project_id=project_id).agents

    def task(self, tasks: Iterable[Any], task_id: str, *, project_id: str | None = None) -> DashboardTaskSummary:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        for item in self.snapshot(tasks, project_id=project_id).tasks:
            if item.task_id == task_id:
                return item
        raise KeyError(task_id)


DEFAULT_DASHBOARD_QUERY = DashboardQuery()
