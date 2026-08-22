from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .workflow_event import WorkflowEvent
from .workflow_event_log import WorkflowEventConflictError


class WorkflowEventPersistenceAdapter:
    """Filesystem-backed persistence for immutable workflow events."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(event_id: str) -> str:
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        if Path(event_id).name != event_id or event_id in {".", ".."}:
            raise ValueError("event_id must be a simple filename-safe identifier")
        if any(sep in event_id for sep in ("/", "\\")):
            raise ValueError("event_id must not contain path separators")
        return event_id

    def _path(self, event_id: str) -> Path:
        return self.root / f"{self._validate_id(event_id)}.json"

    def save(self, event: WorkflowEvent) -> None:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        path = self._path(event.event_id)
        if path.exists():
            raise FileExistsError(path)
        self._atomic_write(path, event.to_dict(), exclusive=True)

    def save_if_absent(self, event: WorkflowEvent) -> bool:
        if not isinstance(event, WorkflowEvent):
            raise TypeError("event must be a WorkflowEvent")
        path = self._path(event.event_id)
        if path.exists():
            existing = self.load(event.event_id)
            if existing == event:
                return False
            raise WorkflowEventConflictError(
                f"conflicting workflow event for event_id: {event.event_id}"
            )
        self._atomic_write(path, event.to_dict(), exclusive=False)
        return True

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

        pending: list[tuple[Path, str]] = []
        for event_id, event in unique.items():
            path = self._path(event_id)
            if path.exists():
                existing = self.load(event_id)
                if existing != event:
                    raise WorkflowEventConflictError(
                        f"conflicting workflow event for event_id: {event_id}"
                    )
                continue
            pending.append(
                (path, json.dumps(event.to_dict(), ensure_ascii=False, indent=2))
            )

        staged: list[tuple[Path, Path]] = []
        created: list[Path] = []
        try:
            for path, payload in pending:
                fd, temporary = tempfile.mkstemp(
                    prefix=f".{path.stem}-", suffix=".tmp", dir=self.root, text=True
                )
                temp_path = Path(temporary)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
                staged.append((temp_path, path))

            for temp_path, path in staged:
                os.replace(temp_path, path)
                created.append(path)
            return len(pending)
        except Exception:
            for temp_path, _ in staged:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            for path in created:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise

    def load(self, event_id: str) -> WorkflowEvent:
        path = self._path(event_id)
        if not path.is_file():
            raise KeyError(event_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            event = WorkflowEvent.from_dict(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid workflow event: {event_id}") from exc
        if event.event_id != event_id:
            raise ValueError("workflow event identity does not match filename")
        return event

    def _load_all_events(self) -> list[WorkflowEvent]:
        """Load every persisted event and fail fast on a corrupt event file."""
        return [self.load(event_id) for event_id in self.list_ids()]

    @staticmethod
    def _sort_all(events: Iterable[WorkflowEvent]) -> list[WorkflowEvent]:
        return sorted(
            events,
            key=lambda event: (
                event.project_id,
                event.task_id or "",
                event.occurred_at,
                event.event_id,
            ),
        )

    @staticmethod
    def _sort_scoped(events: Iterable[WorkflowEvent]) -> list[WorkflowEvent]:
        return sorted(events, key=lambda event: (event.occurred_at, event.event_id))

    def list_all(self) -> list[WorkflowEvent]:
        """Return all persisted events using WorkflowEventLog's global order."""
        return self._sort_all(self._load_all_events())

    def list_for_project(self, project_id: str) -> list[WorkflowEvent]:
        """Return one project's persisted events in deterministic chronological order."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        return self._sort_scoped(
            event for event in self._load_all_events() if event.project_id == project_id
        )

    def list_for_task(self, task_id: str) -> list[WorkflowEvent]:
        """Return one task's persisted events in deterministic chronological order."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        return self._sort_scoped(
            event for event in self._load_all_events() if event.task_id == task_id
        )

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json") if path.is_file())

    def delete(self, event_id: str) -> None:
        path = self._path(event_id)
        if not path.is_file():
            raise KeyError(event_id)
        path.unlink()

    @staticmethod
    def _atomic_write(path: Path, payload: dict, *, exclusive: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if exclusive and path.exists():
            raise FileExistsError(path)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent, text=True
        )
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise
