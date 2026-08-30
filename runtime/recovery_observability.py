from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from runtime.metrics import DEFAULT_METRICS, MetricsRegistry
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


@dataclass(frozen=True)
class RecoveryObservation:
    task_id: str
    event_type: str
    occurred_at: str
    project_id: str


class RecoveryObservability:
    """Emit low-cardinality recovery facts to the existing event/metrics boundary."""

    _EVENTS = {
        "detected": "workflow.recovery.detected",
        "triggered": "workflow.recovery.triggered",
        "rejected": "workflow.recovery.rejected",
        "takeover": "workflow.recovery.takeover",
        "started": "workflow.recovery.started",
        "completed": "workflow.recovery.completed",
        "failed": "workflow.recovery.failed",
    }

    def __init__(
        self,
        event_log: WorkflowEventLog,
        *,
        metrics: MetricsRegistry | None = None,
        project_id: str = "unknown",
        clock=None,
    ) -> None:
        if not isinstance(event_log, WorkflowEventLog):
            raise TypeError("event_log must be a WorkflowEventLog")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        self.event_log = event_log
        self.metrics = metrics or DEFAULT_METRICS
        self.project_id = project_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def emit(self, outcome: str, task_id: str, *, reason: str | None = None, generation: int | None = None) -> RecoveryObservation:
        if outcome not in self._EVENTS:
            raise ValueError(f"unsupported recovery observation: {outcome}")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        occurred_at = self._clock().isoformat()
        payload = {"outcome": outcome}
        if reason is not None:
            payload["reason"] = str(reason)
        if generation is not None:
            payload["generation"] = generation
        event = WorkflowEvent(
            event_id=f"RECOVERY-{uuid4().hex}",
            event_type=self._EVENTS[outcome],
            project_id=self.project_id,
            task_id=task_id,
            occurred_at=occurred_at,
            payload=payload,
        )
        self.event_log.append(event)
        self.metrics.inc(
            "workflow.recovery.total",
            labels={"event_type": event.event_type, "outcome": outcome},
        )
        return RecoveryObservation(task_id, event.event_type, occurred_at, self.project_id)

    def detected(self, task_id: str, *, reason: str | None = None) -> RecoveryObservation:
        return self.emit("detected", task_id, reason=reason)

    def triggered(self, task_id: str, *, reason: str | None = None) -> RecoveryObservation:
        return self.emit("triggered", task_id, reason=reason)

    def rejected(self, task_id: str, *, reason: str | None = None) -> RecoveryObservation:
        return self.emit("rejected", task_id, reason=reason)

    def takeover(self, task_id: str, *, generation: int, reason: str | None = None) -> RecoveryObservation:
        return self.emit("takeover", task_id, reason=reason, generation=generation)

    def started(self, task_id: str, *, generation: int) -> RecoveryObservation:
        return self.emit("started", task_id, generation=generation)

    def completed(self, task_id: str, *, generation: int) -> RecoveryObservation:
        return self.emit("completed", task_id, generation=generation)

    def failed(self, task_id: str, *, generation: int, reason: str | None = None) -> RecoveryObservation:
        return self.emit("failed", task_id, reason=reason, generation=generation)


__all__ = ["RecoveryObservation", "RecoveryObservability"]
