from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .workflow_event_log import WorkflowEventLog
from .workflow_event_persistence import WorkflowEventPersistenceAdapter
from .workflow_event_projection import WorkflowEventProjector, WorkflowProjectProjection, WorkflowTaskProjection


@dataclass(frozen=True)
class WorkflowEventQueryService:
    """Read-only operational query boundary over a workflow event stream.

    The service deliberately owns no mutable runtime state and never writes to
    persistence. A projection is created once from the supplied event log and
    all query methods return immutable projection objects or scalar facts.
    """

    projection: WorkflowProjectProjection

    @classmethod
    def from_log(
        cls,
        event_log: WorkflowEventLog,
        *,
        project_id: str,
    ) -> "WorkflowEventQueryService":
        if not isinstance(event_log, WorkflowEventLog):
            raise TypeError("event_log must be a WorkflowEventLog")
        return cls(WorkflowEventProjector.project(event_log, project_id=project_id))

    @classmethod
    def from_persistence(
        cls,
        persistence: WorkflowEventPersistenceAdapter,
        *,
        project_id: str,
    ) -> "WorkflowEventQueryService":
        """Build a query service from an independently rehydrated event stream."""
        if not isinstance(persistence, WorkflowEventPersistenceAdapter):
            raise TypeError("persistence must be a WorkflowEventPersistenceAdapter")
        log = persistence.load_log()
        return cls.from_log(log, project_id=project_id)

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
    def last_event(self) -> tuple[str | None, str | None, str | None]:
        return (
            self.projection.last_event_id,
            self.projection.last_event_type,
            self.projection.last_occurred_at,
        )

    def task(self, task_id: str) -> WorkflowTaskProjection:
        return self.projection.task(task_id)

    def lifecycle(self, task_id: str | None = None) -> str:
        if task_id is None:
            return self.projection.lifecycle_status
        return self.task(task_id).lifecycle_status

    def retry(self, task_id: str) -> dict[str, int | None]:
        state = self.task(task_id)
        return {
            "retry_attempt": state.retry_attempt,
            "max_retries": state.max_retries,
        }

    def error(self, task_id: str) -> str | None:
        return self.task(task_id).error

    def review_status(self, task_id: str) -> str | None:
        return self.task(task_id).review_status

    def as_dict(self) -> dict[str, Any]:
        """Return a detached diagnostic representation of the projection."""
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
