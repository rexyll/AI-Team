from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .project_persistence import ProjectPersistenceAdapter
from .reviewer_metrics import ReviewerReliabilityMetrics, project_reviewer_reliability
from .workflow_event_log import WorkflowEventLog
from .workflow_event_persistence import WorkflowEventPersistenceAdapter
from .workflow_event_projection import WorkflowEventProjector, WorkflowProjectProjection, WorkflowTaskProjection


_HISTORICAL_ERROR_EVENTS = {
    "developer_failed",
    "developer_invalid_result",
    "tester_failed",
    "tester_invalid_result",
    "tester_invalid_evidence",
    "reviewer_failed",
    "reviewer_invalid_result",
    "reviewer_invalid_evidence",
    "task_failed",
}


@dataclass(frozen=True)
class WorkflowEventQueryService:
    """Read-only operational query boundary over a workflow event stream."""

    projection: WorkflowProjectProjection
    _reviewer_metrics: ReviewerReliabilityMetrics = ReviewerReliabilityMetrics()
    _historical_errors: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def _require_non_empty_string(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value

    @staticmethod
    def _collect_historical_errors(events: list) -> tuple[tuple[str, str], ...]:
        """Capture the latest failure diagnostic per task without changing live state."""
        latest: dict[str, str] = {}
        for event in events:
            if event.task_id is None or event.event_type not in _HISTORICAL_ERROR_EVENTS:
                continue
            value = event.payload.get("error") or event.payload.get("message")
            if isinstance(value, str) and value:
                latest[event.task_id] = value
        return tuple(sorted(latest.items()))

    @classmethod
    def from_log(cls, event_log: WorkflowEventLog, *, project_id: str) -> "WorkflowEventQueryService":
        if not isinstance(event_log, WorkflowEventLog):
            raise TypeError("event_log must be a WorkflowEventLog")
        project_id = cls._require_non_empty_string(project_id, "project_id")
        selected = event_log.list_for_project(project_id)
        return cls(
            WorkflowEventProjector.project(selected, project_id=project_id, ordered=True),
            project_reviewer_reliability(selected, project_id=project_id, ordered=True),
            cls._collect_historical_errors(selected),
        )

    @classmethod
    def from_persistence(cls, persistence: WorkflowEventPersistenceAdapter, *, project_id: str) -> "WorkflowEventQueryService":
        if not isinstance(persistence, WorkflowEventPersistenceAdapter):
            raise TypeError("persistence must be a WorkflowEventPersistenceAdapter")
        project_id = cls._require_non_empty_string(project_id, "project_id")
        return cls.from_log(persistence.load_log(), project_id=project_id)

    @classmethod
    def from_persisted_project(
        cls,
        project_persistence: ProjectPersistenceAdapter,
        event_persistence: WorkflowEventPersistenceAdapter,
        *,
        project_id: str,
    ) -> "WorkflowEventQueryService":
        if not isinstance(project_persistence, ProjectPersistenceAdapter):
            raise TypeError("project_persistence must be a ProjectPersistenceAdapter")
        if not isinstance(event_persistence, WorkflowEventPersistenceAdapter):
            raise TypeError("event_persistence must be a WorkflowEventPersistenceAdapter")
        project_id = cls._require_non_empty_string(project_id, "project_id")
        project_persistence.load(project_id)
        event_log = event_persistence.load_log()
        selected = event_log.list_for_project(project_id)
        if len(event_log) > 0 and not selected:
            raise ValueError(f"no events for project: {project_id}")
        return cls(
            WorkflowEventProjector.project(selected, project_id=project_id, ordered=True),
            project_reviewer_reliability(selected, project_id=project_id, ordered=True),
            cls._collect_historical_errors(selected),
        )

    @property
    def project_id(self) -> str:
        return self.projection.project_id

    @property
    def lifecycle_status(self) -> str:
        return self.projection.lifecycle_status

    @property
    def resumed(self) -> bool:
        return self.projection.resumed

    @property
    def reviewer_metrics(self) -> ReviewerReliabilityMetrics:
        """Immutable Reviewer Reliability metrics derived from the event stream."""
        return self._reviewer_metrics

    @property
    def last_event(self) -> tuple[str | None, str | None, str | None]:
        return (self.projection.last_event_id, self.projection.last_event_type, self.projection.last_occurred_at)

    def task(self, task_id: str) -> WorkflowTaskProjection:
        task_id = self._require_non_empty_string(task_id, "task_id")
        return self.projection.task(task_id)

    def lifecycle(self, task_id: str | None = None) -> str:
        return self.projection.lifecycle_status if task_id is None else self.task(task_id).lifecycle_status

    def retry(self, task_id: str) -> dict[str, int]:
        state = self.task(task_id)
        return {"retry_attempt": state.retry_attempt, "max_retries": state.max_retries}

    def error(self, task_id: str) -> str | None:
        """Return the latest recorded failure diagnostic, including retried failures."""
        task_id = self._require_non_empty_string(task_id, "task_id")
        self.task(task_id)
        return dict(self._historical_errors).get(task_id)

    def review_status(self, task_id: str) -> str | None:
        return self.task(task_id).review_status

    def as_dict(self) -> dict[str, Any]:
        """Return a detached diagnostic representation of the lifecycle projection."""
        return {
            "project_id": self.projection.project_id,
            "lifecycle_status": self.projection.lifecycle_status,
            "last_event_id": self.projection.last_event_id,
            "last_event_type": self.projection.last_event_type,
            "last_occurred_at": self.projection.last_occurred_at,
            "resumed": self.projection.resumed,
            "tasks": [
                {
                    "project_id": task.project_id,
                    "task_id": task.task_id,
                    "lifecycle_status": task.lifecycle_status,
                    "last_event_id": task.last_event_id,
                    "last_event_type": task.last_event_type,
                    "last_occurred_at": task.last_occurred_at,
                    "retry_attempt": task.retry_attempt,
                    "max_retries": task.max_retries,
                    "error": task.error,
                    "review_status": task.review_status,
                }
                for task in self.projection.tasks
            ],
        }
