from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime.task import Task
from runtime.task_status import TaskStatus


@dataclass(frozen=True)
class QuarantinedCheckpoint:
    task_id: str
    reason: str
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class CheckpointRecoveryResult:
    tasks: tuple[Task, ...]
    quarantined: tuple[QuarantinedCheckpoint, ...]


class CheckpointQuarantine:
    """Validate checkpoint snapshots and isolate invalid entries."""

    def recover(self, snapshots: list[dict[str, Any]]) -> CheckpointRecoveryResult:
        tasks: list[Task] = []
        quarantined: list[QuarantinedCheckpoint] = []
        seen: set[str] = set()
        for snapshot in snapshots:
            task_id = snapshot.get("id") if isinstance(snapshot, dict) else "<unknown>"
            reason = self._validate(snapshot, seen)
            if reason is not None:
                quarantined.append(
                    QuarantinedCheckpoint(task_id, reason, deepcopy(snapshot) if isinstance(snapshot, dict) else {})
                )
                continue
            seen.add(task_id)
            tasks.append(Task.from_dict(deepcopy(snapshot)))
        return CheckpointRecoveryResult(tuple(tasks), tuple(quarantined))

    @staticmethod
    def _validate(snapshot: Any, seen: set[str]) -> str | None:
        if not isinstance(snapshot, dict):
            return "checkpoint must be a mapping"
        task_id = snapshot.get("id")
        if not isinstance(task_id, str) or not task_id:
            return "checkpoint id is required"
        if task_id in seen:
            return "duplicate checkpoint id"
        status = snapshot.get("status")
        valid_statuses = {item.value for item in TaskStatus}
        if status not in valid_statuses:
            return "invalid task status"
        required = ("title", "description", "role")
        missing = [key for key in required if key not in snapshot]
        if missing:
            return "missing required fields: " + ", ".join(missing)
        return None
