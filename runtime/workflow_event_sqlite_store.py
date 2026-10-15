from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .workflow_event import WorkflowEvent
from .workflow_event_log import WorkflowEventConflictError, WorkflowEventLog


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    task_id     TEXT,
    occurred_at TEXT NOT NULL,
    sequence    INTEGER,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_project   ON events (project_id);
CREATE INDEX IF NOT EXISTS idx_events_task      ON events (task_id);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_sequence  ON events (sequence);
CREATE INDEX IF NOT EXISTS idx_events_occurred  ON events (occurred_at);
"""

# Mirrors the filesystem adapter's projection of a NULL task_id in list_all().
_UNSET_TASK_KEY = "CHAR(65535)"


class SqliteWorkflowEventStore:
    """SQLite-backed persistence for immutable workflow events.

    Implements the exact ``WorkflowEventPersistenceAdapter`` contract as an
    optional scalable backend: file-per-event JSON stays the default; projects
    that expect large event volumes may select this store instead. Event
    payloads remain the authoritative documents (stored as JSON, indexed by
    scalar columns for query latency), so round-trips and recovery behave
    identically across both backends.

    Unlike the filesystem adapter, event ids are only required to be non-empty
    strings: SQLite has no path semantics for them.
    """

    def __init__(self, path: str | Path, *, timeout: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        self._timeout = float(timeout)
        self._write_lock = threading.RLock()
        connection = self._connect()
        try:
            connection.executescript(_SCHEMA)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=self._timeout)

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Commit-on-success, rollback-on-error connection scope.

        ``immediate`` takes the write lock up front so the check-then-insert
        sequences below are atomic across processes, not just threads.
        """
        connection = self._connect()
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_id(event_id: str) -> str:
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        return event_id

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> WorkflowEvent:
        try:
            payload = json.loads(row["payload"])
            event = WorkflowEvent.from_dict(payload)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid workflow event: {row['event_id']}") from exc
        if event.event_id != row["event_id"]:
            raise ValueError("workflow event identity does not match stored id")
        return event

    @staticmethod
    def _existing_payload(connection: sqlite3.Connection, event_id: str) -> str | None:
        row = connection.execute(
            "SELECT payload FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row[0] if row is not None else None

    @staticmethod
    def _insert(connection: sqlite3.Connection, event: WorkflowEvent) -> int:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO events "
            "(event_id, event_type, project_id, task_id, occurred_at, sequence, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.event_type,
                event.project_id,
                event.task_id,
                event.occurred_at,
                event.sequence,
                json.dumps(event.to_dict(), ensure_ascii=False),
            ),
        )
        return cursor.rowcount

    def save(self, event: WorkflowEvent) -> None:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        with self._write_lock, self._transaction(immediate=True) as connection:
            if self._existing_payload(connection, event.event_id) is not None:
                raise FileExistsError(event.event_id)
            self._insert(connection, event)

    def save_if_absent(self, event: WorkflowEvent) -> bool:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        with self._write_lock, self._transaction(immediate=True) as connection:
            stored_payload = self._existing_payload(connection, event.event_id)
            if stored_payload is not None:
                if self._stored_event(event.event_id, stored_payload) == event:
                    return False
                raise WorkflowEventConflictError(
                    f"conflicting workflow event for event_id: {event.event_id}"
                )
            self._insert(connection, event)
            return True

    @staticmethod
    def _stored_event(event_id: str, payload_text: str) -> WorkflowEvent:
        try:
            event = WorkflowEvent.from_dict(json.loads(payload_text))
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid workflow event: {event_id}") from exc
        if event.event_id != event_id:
            raise ValueError("workflow event identity does not match stored id")
        return event

    def save_if_absent_many(self, events: Iterable[WorkflowEvent]) -> int:
        incoming = list(events)
        for event in incoming:
            if not isinstance(event, WorkflowEvent):
                raise TypeError("events must contain WorkflowEvent values")

        unique: dict[str, WorkflowEvent] = {}
        for event in incoming:
            previous = unique.get(event.event_id)
            if previous is not None and previous != event:
                raise WorkflowEventConflictError(
                    f"conflicting workflow event for event_id: {event.event_id}"
                )
            unique[event.event_id] = event

        with self._write_lock, self._transaction(immediate=True) as connection:
            created = 0
            for event_id, event in unique.items():
                stored_payload = self._existing_payload(connection, event_id)
                if stored_payload is not None:
                    if self._stored_event(event_id, stored_payload) != event:
                        raise WorkflowEventConflictError(
                            f"conflicting workflow event for event_id: {event_id}"
                        )
                    continue
                created += self._insert(connection, event)
            return created

    def load(self, event_id: str) -> WorkflowEvent:
        self._validate_id(event_id)
        with self._read() as connection:
            row = connection.execute(
                "SELECT payload FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return self._stored_event(event_id, row[0])

    def load_log(self) -> WorkflowEventLog:
        log = WorkflowEventLog()
        log.merge(self.list_all())
        return log

    def list_all(self) -> list[WorkflowEvent]:
        """All events ordered like the filesystem adapter's query contract."""
        with self._read() as connection:
            rows = connection.execute(
                "SELECT event_id, payload FROM events "
                f"ORDER BY project_id, COALESCE(task_id, {_UNSET_TASK_KEY}), "
                "occurred_at, event_id"
            ).fetchall()
        return [self._stored_event(row[0], row[1]) for row in rows]

    def list_for_project(self, project_id: str) -> list[WorkflowEvent]:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        with self._read() as connection:
            rows = connection.execute(
                "SELECT event_id, payload FROM events WHERE project_id = ? "
                "ORDER BY occurred_at, event_id",
                (project_id,),
            ).fetchall()
        return [self._stored_event(row[0], row[1]) for row in rows]

    def list_for_task(self, task_id: str) -> list[WorkflowEvent]:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._read() as connection:
            rows = connection.execute(
                "SELECT event_id, payload FROM events WHERE task_id = ? "
                "ORDER BY occurred_at, event_id",
                (task_id,),
            ).fetchall()
        return [self._stored_event(row[0], row[1]) for row in rows]

    def list_ids(self) -> list[str]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT event_id FROM events ORDER BY event_id"
            ).fetchall()
        return [row[0] for row in rows]

    def count(self) -> int:
        """Return the number of stored events (backend-specific helper)."""
        with self._read() as connection:
            row = connection.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0])

    def delete(self, event_id: str) -> None:
        self._validate_id(event_id)
        with self._write_lock, self._transaction(immediate=True) as connection:
            cursor = connection.execute(
                "DELETE FROM events WHERE event_id = ?", (event_id,)
            )
            if cursor.rowcount == 0:
                raise KeyError(event_id)
