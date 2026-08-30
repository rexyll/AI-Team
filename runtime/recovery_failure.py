from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from runtime.task import Task


@dataclass(frozen=True)
class RecoveryFailure:
    task_id: str
    reason: str
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class IsolatedRecoveryResult:
    tasks: tuple[Task, ...]
    failures: tuple[RecoveryFailure, ...]


class RecoveryFailureIsolation:
    """Recover checkpoints independently so one unexpected failure cannot abort others."""

    def recover(
        self,
        snapshots: list[dict[str, Any]],
        *,
        recover_one: Callable[[dict[str, Any]], Task] | None = None,
    ) -> IsolatedRecoveryResult:
        recover_one = recover_one or self._default_recover
        tasks: list[Task] = []
        failures: list[RecoveryFailure] = []
        seen: set[str] = set()
        for snapshot in snapshots:
            task_id = snapshot.get("id") if isinstance(snapshot, dict) else "<unknown>"
            if task_id in seen:
                failures.append(RecoveryFailure(task_id, "duplicate checkpoint id", deepcopy(snapshot) if isinstance(snapshot, dict) else {}))
                continue
            seen.add(task_id)
            try:
                tasks.append(recover_one(deepcopy(snapshot)))
            except Exception as exc:
                failures.append(
                    RecoveryFailure(task_id, f"recovery failed: {type(exc).__name__}: {exc}", deepcopy(snapshot) if isinstance(snapshot, dict) else {})
                )
        return IsolatedRecoveryResult(tuple(tasks), tuple(failures))

    @staticmethod
    def _default_recover(snapshot: dict[str, Any]) -> Task:
        return Task.from_dict(snapshot)
