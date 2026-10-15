from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from runtime.process_lock import exclusive_process_lock
from security.secrets import redact_mapping, redact_value


@dataclass(frozen=True)
class TaskResultRecord:
    task_id: str
    delivery_key: str
    status: str
    result: dict[str, Any]


@dataclass(frozen=True)
class TaskResultDecision:
    accepted: bool
    duplicate: bool
    status: str
    record: TaskResultRecord


class DurableTaskResultStore:
    """Durable, task-scoped result sink used at the commit boundary."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        safe = task_id.replace("/", "_").replace(chr(92), "_")
        return self.root / f"task-result-{safe}.json"

    def _lock_path(self, task_id: str) -> Path:
        safe = task_id.replace("/", "_").replace(chr(92), "_")
        return self.root / f".task-result-{safe}.lock"

    def get(self, task_id: str) -> TaskResultRecord | None:
        with exclusive_process_lock(self._lock_path(task_id)), self._lock:
            return self._load(task_id)

    def commit(
        self,
        task_id: str,
        delivery_key: str,
        result: dict[str, Any],
        *,
        status: str = "completed",
    ) -> TaskResultDecision:
        if not isinstance(delivery_key, str) or not delivery_key.strip():
            raise ValueError("delivery_key must be a non-empty string")
        if not isinstance(result, dict):
            raise TypeError("result must be a dictionary")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("status must be a non-empty string")

        with exclusive_process_lock(self._lock_path(task_id)), self._lock:
            current = self._load(task_id)
            if current is not None:
                if current.delivery_key == delivery_key:
                    return TaskResultDecision(False, True, current.status, current)
                raise ValueError(
                    f"Task {task_id} already has a committed result for delivery "
                    f"{current.delivery_key}"
                )

            sanitized = redact_mapping(result)
            record = TaskResultRecord(
                task_id=task_id,
                delivery_key=delivery_key,
                status=status,
                result=sanitized,
            )
            self._write(record)
            return TaskResultDecision(True, False, status, record)

    def _load(self, task_id: str) -> TaskResultRecord | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Corrupt task result: {task_id}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Corrupt task result: {task_id}")
        stored_task_id = data.get("task_id")
        delivery_key = data.get("delivery_key")
        status = data.get("status")
        result = data.get("result")
        if stored_task_id != task_id or not isinstance(delivery_key, str) or not isinstance(status, str) or not isinstance(result, dict):
            raise ValueError(f"Corrupt task result: {task_id}")
        return TaskResultRecord(stored_task_id, delivery_key, status, redact_mapping(result))

    def _write(self, record: TaskResultRecord) -> None:
        path = self._path(record.task_id)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "task_id": record.task_id,
                    "delivery_key": record.delivery_key,
                    "status": record.status,
                    "result": record.result,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
