from __future__ import annotations

import threading
from typing import Any, Iterable, Protocol

from .workflow_event import WorkflowEvent


class WorkflowEventPersistenceSink(Protocol):
    """Minimal durable-sink contract required by the in-memory event log."""

    def save_if_absent(self, event: WorkflowEvent) -> bool:
        ...


class WorkflowEventConflictError(ValueError):
    """Raised when one event id maps to different immutable events."""


class WorkflowEventLog:
    """Ordered in-memory index of immutable workflow events."""

    def __init__(self, persistence_sink: WorkflowEventPersistenceSink | None = None) -> None:
        if persistence_sink is not None and not callable(getattr(persistence_sink, "save_if_absent", None)):
            raise TypeError("persistence_sink must provide save_if_absent(event) or be None")
        self._events: dict[str, WorkflowEvent] = {}
        self._append_sequence: dict[str, int] = {}
        self._next_append_sequence = 0
        self._all_index: list[WorkflowEvent] | None = None
        self._project_indexes: dict[str, list[WorkflowEvent]] = {}
        self._task_indexes: dict[str, list[WorkflowEvent]] = {}
        self._persistence_sink = persistence_sink
        self._lock = threading.RLock()

    @property
    def persistence_sink(self) -> WorkflowEventPersistenceSink | None:
        return self._persistence_sink

    def set_persistence_sink(self, persistence_sink: WorkflowEventPersistenceSink | None) -> None:
        if persistence_sink is not None and not callable(getattr(persistence_sink, "save_if_absent", None)):
            raise TypeError("persistence_sink must provide save_if_absent(event) or be None")
        with self._lock:
            self._persistence_sink = persistence_sink

    @staticmethod
    def _conflict(event_id: str) -> WorkflowEventConflictError:
        return WorkflowEventConflictError(f"conflicting workflow event for event_id: {event_id}")

    def _persist_if_configured(self, event: WorkflowEvent) -> None:
        if self._persistence_sink is not None:
            self._persistence_sink.save_if_absent(event)

    def _invalidate_indexes(self) -> None:
        self._all_index = None
        self._project_indexes.clear()
        self._task_indexes.clear()

    def _record_event(self, event: WorkflowEvent) -> None:
        self._events[event.event_id] = event
        self._append_sequence[event.event_id] = self._next_append_sequence
        self._next_append_sequence += 1

    def append(self, event: WorkflowEvent) -> None:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        with self._lock:
            if event.event_id in self._events:
                raise ValueError(f"event_id already exists: {event.event_id}")
            self._persist_if_configured(event)
            self._record_event(event)
            self._invalidate_indexes()

    def append_if_absent(self, event: WorkflowEvent) -> bool:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is None:
                self._persist_if_configured(event)
                self._record_event(event)
                self._invalidate_indexes()
                return True
            if existing == event:
                return False
            raise self._conflict(event.event_id)

    def merge(self, events: Iterable[WorkflowEvent]) -> int:
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
            for event in pending.values():
                self._record_event(event)
            if pending:
                self._invalidate_indexes()
            return len(pending)

    @staticmethod
    def _global_sort_key(event: WorkflowEvent) -> tuple[str, str, str, str]:
        return (
            event.project_id,
            event.task_id if event.task_id is not None else "\uffff",
            event.occurred_at,
            event.event_id,
        )

    def _project_sort_key(self, event: WorkflowEvent) -> tuple[int, str, str]:
        # Project queries have a deterministic persisted ordering: timestamp,
        # then event id. ``project.resumed`` remains a lifecycle exception and
        # is kept after the ordinary project events at the same timestamp.
        return (
            1 if event.event_type == "project.resumed" else 0,
            event.occurred_at,
            event.event_id,
        )

    def list_all(self) -> list[WorkflowEvent]:
        with self._lock:
            if self._all_index is None:
                self._all_index = sorted(self._events.values(), key=self._global_sort_key)
            return list(self._all_index)

    def list_for_project(self, project_id: str) -> list[WorkflowEvent]:
        with self._lock:
            cached = self._project_indexes.get(project_id)
            if cached is None:
                cached = sorted(
                    (event for event in self._events.values() if event.project_id == project_id),
                    key=self._project_sort_key,
                )
                self._project_indexes[project_id] = cached
            return list(cached)

    def _task_sort_key(self, event: WorkflowEvent) -> tuple[str, int, int | str]:
        sequence = self._append_sequence.get(event.event_id)
        if sequence is not None:
            return (event.occurred_at, 0, sequence)
        return (event.occurred_at, 1, event.event_id)

    def list_for_task(self, task_id: str) -> list[WorkflowEvent]:
        with self._lock:
            cached = self._task_indexes.get(task_id)
            if cached is None:
                cached = sorted(
                    (event for event in self._events.values() if event.task_id == task_id),
                    key=self._task_sort_key,
                )
                self._task_indexes[task_id] = cached
            return list(cached)

    def get(self, event_id: str) -> WorkflowEvent:
        with self._lock:
            return self._events[event_id]

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
