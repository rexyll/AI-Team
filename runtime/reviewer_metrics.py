from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .workflow_event import WorkflowEvent
from .workflow_event_log import WorkflowEventLog


@dataclass(frozen=True)
class ReviewerReliabilityMetrics:
    """Immutable reviewer reliability metrics reconstructed from workflow events."""

    primary_attempts: int = 0
    primary_successes: int = 0
    primary_failures: int = 0
    fallback_attempts: int = 0
    fallback_successes: int = 0
    fallback_failures: int = 0
    empty_responses: int = 0
    recovery_count: int = 0
    recovery_success_count: int = 0
    recovery_exhausted_count: int = 0

    @property
    def primary_success_rate(self) -> float:
        return self.primary_successes / self.primary_attempts if self.primary_attempts else 0.0

    @property
    def fallback_activation_rate(self) -> float:
        return self.fallback_attempts / self.primary_attempts if self.primary_attempts else 0.0

    @property
    def fallback_recovery_success_rate(self) -> float:
        return self.recovery_success_count / self.recovery_count if self.recovery_count else 0.0

    def to_dict(self) -> dict[str, int | float]:
        return {
            "primary_attempts": self.primary_attempts,
            "primary_successes": self.primary_successes,
            "primary_failures": self.primary_failures,
            "fallback_attempts": self.fallback_attempts,
            "fallback_successes": self.fallback_successes,
            "fallback_failures": self.fallback_failures,
            "empty_responses": self.empty_responses,
            "recovery_count": self.recovery_count,
            "recovery_success_count": self.recovery_success_count,
            "recovery_exhausted_count": self.recovery_exhausted_count,
            "primary_success_rate": self.primary_success_rate,
            "fallback_activation_rate": self.fallback_activation_rate,
            "fallback_recovery_success_rate": self.fallback_recovery_success_rate,
        }


def _reviewer_reliability(payload: dict) -> dict:
    result = payload.get("result")
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    if not isinstance(data, dict):
        return {}
    metrics = data.get("reviewer_reliability")
    return metrics if isinstance(metrics, dict) else {}


def _reviewer_execution(payload: dict) -> dict:
    result = payload.get("result")
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    if not isinstance(data, dict):
        return {}
    execution = data.get("reviewer_execution")
    return execution if isinstance(execution, dict) else {}


def project_reviewer_reliability(
    events: WorkflowEventLog | Iterable[WorkflowEvent],
    *,
    project_id: str,
) -> ReviewerReliabilityMetrics:
    """Aggregate reviewer counters from immutable workflow facts.

    The aggregation prefers the cumulative snapshot emitted by the resilient
    reviewer. This makes the result stable even when one workflow run produces
    multiple reviewer events for the same task.
    """
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    if isinstance(events, WorkflowEventLog):
        selected = events.list_for_project(project_id)
    else:
        selected = [event for event in events if event.project_id == project_id]
        if any(not isinstance(event, WorkflowEvent) for event in selected):
            raise TypeError("events must contain WorkflowEvent values")
        selected.sort(key=lambda event: (event.occurred_at, event.event_id))

    latest_by_task: dict[str, dict] = {}
    recovery_events: list[WorkflowEvent] = []
    retry_events: dict[str, int] = {}
    exhausted_tasks: set[str] = set()
    recovery_success_tasks: set[str] = set()

    for event in selected:
        if event.event_type == "reviewer_fallback":
            recovery_events.append(event)
            if event.task_id is not None:
                latest_by_task[event.task_id] = _reviewer_reliability(event.payload)
        elif event.event_type == "reviewer_retry" and event.task_id is not None:
            retry_events[event.task_id] = retry_events.get(event.task_id, 0) + 1
        elif event.event_type == "reviewer_approved" and event.task_id is not None:
            execution = _reviewer_execution(event.payload)
            if execution.get("recovered") is True:
                recovery_success_tasks.add(event.task_id)
            metrics = _reviewer_reliability(event.payload)
            if metrics:
                latest_by_task[event.task_id] = metrics
        elif event.event_type == "task_failed" and event.task_id is not None:
            if retry_events.get(event.task_id, 0) == 0 and event.task_id in latest_by_task:
                exhausted_tasks.add(event.task_id)

    # Also consume ordinary reviewer events, which may be approved without fallback.
    for event in selected:
        if event.event_type in {"reviewer_approved", "reviewer_revision", "reviewer_fallback"} and event.task_id:
            metrics = _reviewer_reliability(event.payload)
            if metrics:
                latest_by_task[event.task_id] = metrics

    if latest_by_task:
        counters = {key: 0 for key in (
            "primary_attempts", "primary_successes", "primary_failures",
            "fallback_attempts", "fallback_successes", "fallback_failures", "empty_responses"
        )}
        for snapshot in latest_by_task.values():
            for key in counters:
                value = snapshot.get(key, 0)
                if isinstance(value, int) and value >= 0:
                    counters[key] += value
    else:
        counters = {key: 0 for key in (
            "primary_attempts", "primary_successes", "primary_failures",
            "fallback_attempts", "fallback_successes", "fallback_failures", "empty_responses"
        )}

    return ReviewerReliabilityMetrics(
        **counters,
        recovery_count=len(recovery_events),
        recovery_success_count=len(recovery_success_tasks),
        recovery_exhausted_count=len(exhausted_tasks),
    )
