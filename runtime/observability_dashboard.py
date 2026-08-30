from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from runtime.tracing import Tracer, DEFAULT_TRACER


_ACTIVE_STATUSES = {"ready", "running", "review_pending", "reviewing", "revision"}


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
    duration_seconds: float | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    recovery_count: int = 0


@dataclass(frozen=True)
class DashboardAgentSummary:
    role: str
    task_count: int
    completed: int
    failed: int
    active: int
    success_rate: float
    average_duration_seconds: float | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    retry_count: int = 0


@dataclass(frozen=True)
class DashboardWorkflowSummary:
    total_tasks: int
    completed: int
    failed: int
    blocked: int
    active: int
    pending: int
    success_rate: float
    average_duration_seconds: float | None = None
    total_duration_seconds: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    recoveries: int = 0


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: str
    project_id: str | None
    workflow: DashboardWorkflowSummary
    agents: tuple[DashboardAgentSummary, ...] = field(default_factory=tuple)
    tasks: tuple[DashboardTaskSummary, ...] = field(default_factory=tuple)


class ObservabilityDashboard:
    """Provider-independent operational read model over runtime state and traces."""

    def __init__(self, *, tracer: Tracer | None = None) -> None:
        self.tracer = tracer or DEFAULT_TRACER

    def snapshot(self, tasks: Iterable[Any], *, project_id: str | None = None) -> DashboardSnapshot:
        task_list = list(tasks)
        summaries: list[DashboardTaskSummary] = []
        for task in task_list:
            if not hasattr(task, "id") or not hasattr(task, "status"):
                raise TypeError("tasks must contain Task-like objects with id and status")
            trace_id, root_span_id, duration, llm_calls, tool_calls = self._trace_summary(task)
            retry_history = getattr(task, "retry_history", []) or []
            recovery_count = sum(bool(item.get("recovery")) for item in getattr(task, "status_history", []) or [] if isinstance(item, dict))
            summaries.append(DashboardTaskSummary(
                task_id=str(task.id), title=str(getattr(task, "title", "")),
                role=str(getattr(task, "role", "unknown")), status=str(task.status),
                trace_id=trace_id, root_span_id=root_span_id,
                retry_count=len(retry_history),
                review_round=int(getattr(task, "review_round", 0) or 0),
                error=getattr(task, "error", None), duration_seconds=duration,
                llm_calls=llm_calls, tool_calls=tool_calls, recovery_count=recovery_count,
            ))

        statuses = Counter(item.status for item in summaries)
        total = len(summaries)
        completed = statuses.get("completed", 0)
        failed = statuses.get("failed", 0)
        blocked = statuses.get("blocked", 0)
        active = sum(statuses.get(s, 0) for s in _ACTIVE_STATUSES)
        pending = statuses.get("pending", 0)
        durations = [item.duration_seconds for item in summaries if item.duration_seconds is not None]
        workflow = DashboardWorkflowSummary(
            total_tasks=total, completed=completed, failed=failed, blocked=blocked,
            active=active, pending=pending, success_rate=completed / total if total else 0.0,
            average_duration_seconds=sum(durations) / len(durations) if durations else None,
            total_duration_seconds=sum(durations),
            llm_calls=sum(item.llm_calls for item in summaries),
            tool_calls=sum(item.tool_calls for item in summaries),
            retries=sum(item.retry_count for item in summaries),
            recoveries=sum(item.recovery_count for item in summaries),
        )

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
        active = sum(item.status in _ACTIVE_STATUSES for item in tasks)
        durations = [item.duration_seconds for item in tasks if item.duration_seconds is not None]
        return DashboardAgentSummary(
            role=role, task_count=len(tasks), completed=completed, failed=failed,
            active=active, success_rate=completed / len(tasks) if tasks else 0.0,
            average_duration_seconds=sum(durations) / len(durations) if durations else None,
            llm_calls=sum(item.llm_calls for item in tasks),
            tool_calls=sum(item.tool_calls for item in tasks),
            retry_count=sum(item.retry_count for item in tasks),
        )

    def _trace_summary(self, task: Any) -> tuple[str | None, str | None, float | None, int, int]:
        task_id = getattr(task, "id", None)
        if not isinstance(task_id, str):
            return None, None, None, 0, 0
        matching = [record for record in self.tracer.snapshot() if record.get("attributes", {}).get("task_id") == task_id]
        if not matching:
            return None, None, None, 0, 0
        roots = [record for record in matching if record.get("parent_span_id") is None]
        root = roots[0] if roots else matching[0]
        duration = root.get("duration_seconds")
        llm_calls = sum(record.get("name", "").startswith("llm.") for record in matching)
        tool_calls = sum(record.get("name", "").startswith("tool.") for record in matching)
        return root.get("trace_id"), root.get("span_id"), duration, llm_calls, tool_calls


DEFAULT_DASHBOARD = ObservabilityDashboard()
