from __future__ import annotations

import threading
from typing import Any, Iterable, Protocol

from .workflow_event import WorkflowEvent


class WorkflowEventPersistenceSink(Protocol):
    """Minimal durable-sink contract required by the in-memory event log."""

    def save_if_absent(self, event: WorkflowEvent) -> bool:
        """Persist an event idempotently and return whether a new record was written."""
        ...


class WorkflowEventConflictError(ValueError):
    """Raised when one event id maps to different immutable events."""


class WorkflowEventLog:
    """Ordered in-memory index of immutable workflow events.

    A persistence sink is optional. When configured, a new event is durably
    persisted before it becomes visible in the in-memory index. A persistence
    failure therefore fails the append operation and does not leave an event in
    memory that the durable sink rejected. Existing in-memory-only callers are
    unchanged when no sink is supplied.

    The index is protected by an instance re-entrant lock so readers can safely
    snapshot the stream while another thread appends or merges events. Query and
    projection callers therefore observe a stable snapshot and never mutate the
    log.
    """

    def __init__(self, persistence_sink: WorkflowEventPersistenceSink | None = None) -> None:
        if persistence_sink is not None and not callable(getattr(persistence_sink, "save_if_absent", None)):
            raise TypeError("persistence_sink must provide save_if_absent(event) or be None")
        self._events: dict[str, WorkflowEvent] = {}
        self._persistence_sink = persistence_sink
        self._lock = threading.RLock()

    @property
    def persistence_sink(self) -> WorkflowEventPersistenceSink | None:
        return self._persistence_sink

    def set_persistence_sink(self, persistence_sink: WorkflowEventPersistenceSink | None) -> None:
        """Attach or detach the optional durable event sink."""
        if persistence_sink is not None and not callable(getattr(persistence_sink, "save_if_absent", None)):
            raise TypeError("persistence_sink must provide save_if_absent(event) or be None")
        with self._lock:
            self._persistence_sink = persistence_sink

    @staticmethod
    def _conflict(event_id: str) -> WorkflowEventConflictError:
        return WorkflowEventConflictError(
            f"conflicting workflow event for event_id: {event_id}"
        )

    def _persist_if_configured(self, event: WorkflowEvent) -> None:
        if self._persistence_sink is not None:
            self._persistence_sink.save_if_absent(event)

    def append(self, event: WorkflowEvent) -> None:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        with self._lock:
            if event.event_id in self._events:
                raise ValueError(f"event_id already exists: {event.event_id}")
            self._persist_if_configured(event)
            self._events[event.event_id] = event

    def append_if_absent(self, event: WorkflowEvent) -> bool:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is None:
                self._persist_if_configured(event)
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

        with self._lock:
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

            if self._persistence_sink is not None:
                self._persistence_sink.save_if_absent_many(pending.values())
            self._events.update(pending)
            return len(pending)

    @staticmethod
    def _global_sort_key(event: WorkflowEvent) -> tuple[str, str, str, str]:
        """Keep project-level lifecycle events after task events for global views."""
        return (
            event.project_id,
            event.task_id if event.task_id is not None else "\uffff",
            event.occurred_at,
            event.event_id,
        )

    @staticmethod
    def _project_sort_key(event: WorkflowEvent) -> tuple[int, str, str]:
        """Order a project's resumed marker after the recovered event stream."""
        return (
            1 if event.event_type == "project.resumed" else 0,
            event.occurred_at,
            event.event_id,
        )

    def list_all(self) -> list[WorkflowEvent]:
        with self._lock:
            return sorted(self._events.values(), key=self._global_sort_key)

    def list_for_project(self, project_id: str) -> list[WorkflowEvent]:
        with self._lock:
            return sorted(
                (event for event in self._events.values() if event.project_id == project_id),
                key=self._project_sort_key,
            )

    def list_for_task(self, task_id: str) -> list[WorkflowEvent]:
        """Return task events in deterministic lifecycle order.

        Task event queries intentionally use the same timestamp + event-id
        ordering contract as persisted queries. The timestamp captures the
        workflow lifecycle sequence and the event id supplies a deterministic
        tie-breaker when multiple events share the same timestamp. This keeps
        in-memory and durable projections equivalent and avoids depending on
        dictionary insertion order, which can differ after recovery/merge.
        """
        with self._lock:
            return sorted(
                (event for event in self._events.values() if event.task_id == task_id),
                key=lambda event: (event.occurred_at, event.event_id),
            )

    def get(self, event_id: str) -> WorkflowEvent:
        with self._lock:
            try:
                return self._events[event_id]
            except KeyError as exc:
                raise KeyError(event_id) from exc

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def to_dict(self) -> list[dict]:
        with self._lock:
            return [event.to_dict() for event in self._events.values()]

    @classmethod
    def from_dict(cls, payload: list[dict]) -> "WorkflowEventLog":
        if not isinstance(payload, list):
            raise TypeError("workflow event log payload must be a list")
        log = cls()
        log.merge(WorkflowEvent.from_dict(item) for item in payload)
        return log
