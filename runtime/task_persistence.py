"""Persistence adapter for durable Task state.

The adapter deliberately persists only ``Task.to_dict()`` payloads.  Runtime
components remain outside the persistence boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.task import Task


class TaskPersistenceAdapter:
    """Store Tasks as individual JSON documents in a filesystem directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if Path(task_id).name != task_id or task_id in {".", ".."}:
            raise ValueError("task_id must be a simple file-safe identifier")
        return self.root / f"{task_id}.json"

    def save(self, task: Task) -> None:
        if not isinstance(task, Task):
            raise TypeError("TaskPersistenceAdapter.save expects a Task")

        target = self._path(task.id)
        if target.exists():
            raise FileExistsError(f"Task already exists: {task.id}")

        payload = task.to_dict()
        try:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Task payload is not JSON serializable: {task.id}") from exc

        temporary = target.with_name(f".{target.name}.tmp")
        try:
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(target)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise

    def load(self, task_id: str) -> Task:
        target = self._path(task_id)
        if not target.exists():
            raise KeyError(f"Task not found: {task_id}")

        try:
            payload: Any = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Corrupt Task persistence: {task_id}") from exc

        try:
            return Task.from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"Invalid Task persistence: {task_id}") from exc

    def delete(self, task_id: str) -> None:
        target = self._path(task_id)
        if not target.exists():
            raise KeyError(f"Task not found: {task_id}")
        try:
            target.unlink()
        except OSError:
            raise

    def list_ids(self) -> list[str]:
        return sorted(
            path.stem
            for path in self.root.glob("*.json")
            if path.is_file()
        )
