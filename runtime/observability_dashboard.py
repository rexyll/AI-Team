from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from runtime.tracing import Tracer, DEFAULT_TRACER


@dataclass(frozen=True)
class DashboardTaskSummary:
    task_id: str
    title: str
    role: str
    status: str
    trace_id: str | None = None
    root_span_id: str | None = None
    retry_count: int = 0
    review_round: int = 0
    error: str | None = None


@dataclass(frozen=True)
class DashboardAgentSummary:
    role: str
    task_count: int
    completed: int
    failed: int
    active: int
    success_rate: float


@dataclass(frozen=True)
class DashboardWorkflowSummary:
    total_tasks: int
    completed: int
    failed: int
    blocked: int
    active: int
    pending: int
    success_rate: float


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: str
    project_id: str | None
    workflow: DashboardWorkflowSummary
    agents: tuple[DashboardAgentSummary, ...] = field(default_factory=tuple)
    tasks: tuple[DashboardTaskSummary, ...] = field(default_factory=tuple)


class ObservabilityDashboard:
    """Provider-independent read model over authoritative task/runtime state."""

    def __init__(self, *, tracer: Tracer | None = None) -> None:
        self.tracer = tracer or DEFAULT_TRACER

    def snapshot(self, tasks: Iterable[Any], *, project_id: str | None = None) -> DashboardSnapshot:
        task_list = list(tasks)
        summaries: list[DashboardTaskSummary] = []
        for task in task_list:
            if not hasattr(task, "id") or not hasattr(task, "status"):
                raise TypeError("tasks must contain Task-like objects with id and status")
            trace_id, root_span_id = self._trace_identity(task)
            retry_count = len(getattr(task, "retry_history", []) or [])
            summaries.append(DashboardTaskSummary(
                task_id=str(task.id), title=str(getattr(task, "title", "")),
                role=str(getattr(task, "role", "unknown")), status=str(task.status),
                trace_id=trace_id, root_span_id=root_span_id, retry_count=retry_count,
                review_round=int(getattr(task, "review_round", 0) or 0),
                error=getattr(task, "error", None),
            ))

        statuses = Counter(item.status for item in summaries)
        total = len(summaries)
        completed = statuses.get("completed", 0)
        failed = statuses.get("failed", 0)
        blocked = statuses.get("blocked", 0)
        active = sum(statuses.get(s, 0) for s in ("ready", "running", "review_pending", "reviewing", "revision"))
        pending = statuses.get("pending", 0)
        workflow = DashboardWorkflowSummary(total, completed, failed, blocked, active, pending, completed / total if total else 0.0)

        by_role: dict[str, list[DashboardTaskSummary]] = {}
        for item in summaries:
            by_role.setdefault(item.role, []).append(item)
        agents = tuple(self._agent_summary(role, role_tasks) for role, role_tasks in sorted(by_role.items()))
        return DashboardSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            project_id=project_id, workflow=workflow, agents=agents, tasks=tuple(summaries),
        )

    @staticmethod
    def _agent_summary(role: str, tasks: list[DashboardTaskSummary]) -> DashboardAgentSummary:
        completed = sum(item.status == "completed" for item in tasks)
        failed = sum(item.status == "failed" for item in tasks)
        active = sum(item.status in {"ready", "running", "review_pending", "reviewing", "revision"} for item in tasks)
        return DashboardAgentSummary(role, len(tasks), completed, failed, active, completed / len(tasks) if tasks else 0.0)

    def _trace_identity(self, task: Any) -> tuple[str | None, str | None]:
        task_id = getattr(task, "id", None)
        if not isinstance(task_id, str):
            return None, None
        matching = [record for record in self.tracer.snapshot() if record.get("attributes", {}).get("task_id") == task_id]
        if not matching:
            return None, None
        roots = [record for record in matching if record.get("parent_span_id") is None]
        root = roots[0] if roots else matching[0]
        return root.get("trace_id"), root.get("span_id")


DEFAULT_DASHBOARD = ObservabilityDashboard()
