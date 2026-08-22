from __future__ import annotations

from typing import Iterable

from .workflow_event import WorkflowEvent


class WorkflowEventConflictError(ValueError):
    """Raised when one event id maps to different immutable events."""


class WorkflowEventLog:
    """Ordered in-memory index of immutable workflow events."""

    def __init__(self) -> None:
        self._events: dict[str, WorkflowEvent] = {}

    @staticmethod
    def _conflict(event_id: str) -> WorkflowEventConflictError:
        return WorkflowEventConflictError(
            f"conflicting workflow event for event_id: {event_id}"
        )

    def append(self, event: WorkflowEvent) -> None:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        if event.event_id in self._events:
            raise ValueError(f"event_id already exists: {event.event_id}")
        self._events[event.event_id] = event

    def append_if_absent(self, event: WorkflowEvent) -> bool:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        existing = self._events.get(event.event_id)
        if existing is None:
            self._events[event.event_id] = event
            return True
        if existing == event:
            return False
        raise self._conflict(event.event_id)

    def merge(self, events: Iterable[WorkflowEvent]) -> int:
        """Merge events atomically by event-id identity."""
        incoming = list(events)
        for event in incoming:
            if not isinstance(event, WorkflowEvent):
                raise TypeError("events must contain WorkflowEvent values")

        pending: dict[str, WorkflowEvent] = {}
        for event in incoming:
            existing = self._events.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise self._conflict(event.event_id)
                continue
            previous = pending.get(event.event_id)
            if previous is not None and previous != event:
                raise self._conflict(event.event_id)
            pending[event.event_id] = event

        self._events.update(pending)
        return len(pending)

    def list_all(self) -> list[WorkflowEvent]:
        return sorted(
            self._events.values(),
            key=lambda event: (
                event.project_id,
                event.task_id if event.task_id is not None else "\uffff",
                event.occurred_at,
                event.event_id,
            ),
        )

    def list_for_project(self, project_id: str) -> list[WorkflowEvent]:
        return sorted(
            (event for event in self._events.values() if event.project_id == project_id),
            key=lambda event: (event.occurred_at, event.event_id),
        )

    def list_for_task(self, task_id: str) -> list[WorkflowEvent]:
        return sorted(
            (event for event in self._events.values() if event.task_id == task_id),
            key=lambda event: (event.occurred_at, event.event_id),
        )

    def get(self, event_id: str) -> WorkflowEvent:
        try:
            return self._events[event_id]
        except KeyError as exc:
            raise KeyError(event_id) from exc

    def __len__(self) -> int:
        return len(self._events)

    def to_dict(self) -> list[dict]:
        return [event.to_dict() for event in self._events.values()]

    @classmethod
    def from_dict(cls, payload: list[dict]) -> "WorkflowEventLog":
        if not isinstance(payload, list):
            raise TypeError("workflow event log payload must be a list")
        log = cls()
        log.merge(WorkflowEvent.from_dict(item) for item in payload)
        return log
