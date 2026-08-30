from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .workflow_event import WorkflowEvent
from .workflow_event_log import WorkflowEventLog


_KNOWN_TASK_EVENTS = {
    "task_started", "developer_completed", "developer_failed", "tester_skipped",
    "tester_completed", "tester_failed", "review_started", "reviewer_approved",
    "reviewer_revision", "reviewer_fallback", "reviewer_retry", "task_failed",
    "task_retrying", "task_completed",
}

_STATUS_EVENTS = {
    "developer_completed": "completed", "developer_failed": "failed",
    "tester_completed": "completed", "tester_failed": "failed",
    "reviewer_approved": "completed", "reviewer_revision": "revision",
    "task_failed": "failed", "task_completed": "completed",
}


@dataclass(frozen=True)
class WorkflowTaskProjection:
    """Read-only state reconstructed from one task's workflow event stream."""
    project_id: str
    task_id: str
    lifecycle_status: str = "unknown"
    last_event_id: str | None = None
    last_event_type: str | None = None
    last_occurred_at: str | None = None
    retry_attempt: int = 0
    max_retries: int = 0
    error: str | None = None
    review_status: str | None = None


@dataclass(frozen=True)
class WorkflowProjectProjection:
    """Read-only project-level projection containing task projections."""
    project_id: str
    lifecycle_status: str = "unknown"
    last_event_id: str | None = None
    last_event_type: str | None = None
    last_occurred_at: str | None = None
    resumed: bool = False
    tasks: tuple[WorkflowTaskProjection, ...] = ()

    def task(self, task_id: str) -> WorkflowTaskProjection:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise KeyError(task_id)


class WorkflowEventProjector:
    """Deterministically project workflow facts without mutating runtime state."""

    @classmethod
    def project(
        cls,
        events: WorkflowEventLog | Iterable[WorkflowEvent],
        *,
        project_id: str | None = None,
        ordered: bool = False,
    ) -> WorkflowProjectProjection:
        # QueryService can share one stable project-scoped snapshot with other
        # read-only projections. When ordered=True the caller guarantees the
        # input already uses WorkflowEventLog._project_sort_key ordering.
        if isinstance(events, WorkflowEventLog) and project_id is not None:
            ordered_events = events.list_for_project(project_id)
        elif ordered:
            ordered_events = list(events)
            if any(not isinstance(event, WorkflowEvent) for event in ordered_events):
                raise TypeError("events must contain WorkflowEvent values")
        else:
            ordered_events = cls._ordered_events(events)

        if project_id is None:
            project_ids = {event.project_id for event in ordered_events}
            if len(project_ids) != 1:
                raise ValueError("project_id is required for an empty or multi-project event stream")
            project_id = next(iter(project_ids))

        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

        selected = ordered_events if (isinstance(events, WorkflowEventLog) and project_id is not None) or ordered else [
            event for event in ordered_events if event.project_id == project_id
        ]
        if not selected and ordered_events:
            raise ValueError(f"event stream contains no events for project: {project_id}")

        task_states: dict[str, dict[str, object]] = {}
        resumed = False
        for event in selected:
            cls._validate_event(event, project_id)
            if event.event_type == "project.resumed":
                resumed = True
                continue
            if event.task_id is None:
                raise ValueError(f"task lifecycle event requires task_id: {event.event_id}")
            state = task_states.setdefault(event.task_id, {})
            cls._apply_task_event(state, event)

        tasks = tuple(
            WorkflowTaskProjection(
                project_id=project_id,
                task_id=task_id,
                lifecycle_status=str(state.get("lifecycle_status", "unknown")),
                last_event_id=state.get("last_event_id"),
                last_event_type=state.get("last_event_type"),
                last_occurred_at=state.get("last_occurred_at"),
                retry_attempt=int(state.get("retry_attempt", 0)),
                max_retries=int(state.get("max_retries", 0)),
                error=state.get("error"),
                review_status=state.get("review_status"),
            )
            for task_id, state in sorted(task_states.items())
        )

        last = selected[-1] if selected else None
        lifecycle = cls._project_lifecycle(tasks, resumed=resumed)
        return WorkflowProjectProjection(
            project_id=project_id,
            lifecycle_status=lifecycle,
            last_event_id=last.event_id if last else None,
            last_event_type=last.event_type if last else None,
            last_occurred_at=last.occurred_at if last else None,
            resumed=resumed,
            tasks=tasks,
        )

    @classmethod
    def project_task(cls, events: WorkflowEventLog | Iterable[WorkflowEvent], task_id: str, *, project_id: str | None = None) -> WorkflowTaskProjection:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        return cls.project(events, project_id=project_id).task(task_id)

    @staticmethod
    def _ordered_events(events: WorkflowEventLog | Iterable[WorkflowEvent]) -> list[WorkflowEvent]:
        if isinstance(events, WorkflowEventLog):
            return events.list_all()
        materialized = list(events)
        if any(not isinstance(event, WorkflowEvent) for event in materialized):
            raise TypeError("events must contain WorkflowEvent values")
        # A bare iterable has no append-sequence metadata. Use immutable event
        # fields for deterministic replay independent of iterable type.
        return sorted(
            materialized,
            key=lambda event: (
                event.project_id,
                event.task_id if event.task_id is not None else "\uffff",
                event.occurred_at,
                event.event_id,
            ),
        )

    @staticmethod
    def _validate_event(event: WorkflowEvent, project_id: str) -> None:
        if event.project_id != project_id:
            raise ValueError(f"workflow event belongs to another project: {event.event_id}")
        if event.event_type not in _KNOWN_TASK_EVENTS and event.event_type != "project.resumed":
            return
        if event.event_type == "project.resumed":
            if event.task_id is not None:
                raise ValueError(f"project.resumed must not have task_id: {event.event_id}")
            return
        if event.task_id is None:
            raise ValueError(f"task lifecycle event requires task_id: {event.event_id}")
        required_status = _STATUS_EVENTS.get(event.event_type)
        if required_status is not None:
            status = event.payload.get("status")
            if not isinstance(status, str):
                raise ValueError(f"workflow event payload requires status: {event.event_id}")
            if status != required_status:
                raise ValueError(f"workflow event status mismatch for {event.event_id}: expected {required_status}, got {status}")
        if event.event_type == "task_retrying":
            for field in ("status", "retry_attempt", "max_retries", "reason"):
                if field not in event.payload:
                    raise ValueError(f"workflow retry event missing {field}: {event.event_id}")
            if event.payload["status"] != "ready":
                raise ValueError(f"workflow retry event status mismatch: {event.event_id}")
            if not isinstance(event.payload["retry_attempt"], int) or event.payload["retry_attempt"] < 1:
                raise ValueError(f"workflow retry event has invalid retry_attempt: {event.event_id}")
            if not isinstance(event.payload["max_retries"], int) or event.payload["max_retries"] < 0:
                raise ValueError(f"workflow retry event has invalid max_retries: {event.event_id}")
            if not isinstance(event.payload["reason"], str) or not event.payload["reason"]:
                raise ValueError(f"workflow retry event has invalid reason: {event.event_id}")
        if event.event_type == "reviewer_retry":
            attempt = event.payload.get("attempt")
            max_attempts = event.payload.get("max_attempts")
            if not isinstance(attempt, int) or attempt < 1:
                raise ValueError(f"reviewer retry event has invalid attempt: {event.event_id}")
            if not isinstance(max_attempts, int) or max_attempts < 0:
                raise ValueError(f"reviewer retry event has invalid max_attempts: {event.event_id}")

    @staticmethod
    def _apply_task_event(state: dict[str, object], event: WorkflowEvent) -> None:
        event_type = event.event_type
        state["last_event_id"] = event.event_id
        state["last_event_type"] = event_type
        state["last_occurred_at"] = event.occurred_at
        if event_type == "task_started": state["lifecycle_status"] = "running"
        elif event_type == "developer_completed": state["lifecycle_status"] = "review_pending"
        elif event_type == "developer_failed": state.update(lifecycle_status="failed", error=event.payload.get("error") or event.payload.get("message"))
        elif event_type == "tester_skipped": state["lifecycle_status"] = "review_pending"
        elif event_type == "tester_completed": state["lifecycle_status"] = "review_pending"
        elif event_type == "tester_failed": state.update(lifecycle_status="failed", error=event.payload.get("error") or event.payload.get("message"))
        elif event_type == "review_started": state.update(lifecycle_status="reviewing", review_status="started")
        elif event_type == "reviewer_fallback": state.update(lifecycle_status="review_pending", review_status="recovery")
        elif event_type == "reviewer_retry": state.update(lifecycle_status="reviewing", review_status="retrying")
        elif event_type == "reviewer_revision": state.update(lifecycle_status="running", review_status="revision")
        elif event_type == "reviewer_approved": state.update(lifecycle_status="completed", review_status="approved")
        elif event_type == "task_failed": state.update(lifecycle_status="failed", error=event.payload.get("error") or event.payload.get("message"))
        elif event_type == "task_retrying": state.update(lifecycle_status="ready", retry_attempt=event.payload["retry_attempt"], max_retries=event.payload["max_retries"], error=event.payload["reason"])
        elif event_type == "task_completed": state["lifecycle_status"] = "completed"

    @staticmethod
    def _project_lifecycle(tasks: tuple[WorkflowTaskProjection, ...], *, resumed: bool) -> str:
        if not tasks: return "resumed" if resumed else "unknown"
        statuses = {task.lifecycle_status for task in tasks}
        if statuses == {"completed"}: return "completed"
        if "failed" in statuses: return "failed"
        if "running" in statuses or "reviewing" in statuses or "review_pending" in statuses: return "running"
        return "ready"


def replay_workflow_events(events: WorkflowEventLog | Iterable[WorkflowEvent], *, project_id: str | None = None) -> WorkflowProjectProjection:
    """Convenience wrapper for deterministic, side-effect-free event replay."""
    return WorkflowEventProjector.project(events, project_id=project_id)
