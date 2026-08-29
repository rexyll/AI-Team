from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from runtime.multi_process import TaskLease


@dataclass(frozen=True)
class ResultCommitDecision:
    accepted: bool
    reason: str


class ResultCommitFencer:
    """Reject late results unless the submitting worker still owns the task lease."""

    def __init__(self, lease_store) -> None:
        self.lease_store = lease_store

    def validate(self, task_id: str, worker_id: str, lease_id: str) -> ResultCommitDecision:
        owner: TaskLease | None = self.lease_store.owner(task_id)
        if owner is None:
            return ResultCommitDecision(False, "Task has no active worker lease")
        if owner.worker_id != worker_id or owner.lease_id != lease_id:
            return ResultCommitDecision(False, "Worker lease ownership mismatch")
        return ResultCommitDecision(True, "Worker lease ownership verified")

    def commit(
        self,
        task_id: str,
        worker_id: str,
        lease_id: str,
        apply_result: Callable[[], object],
    ) -> object:
        """Atomically validate lease ownership and apply the result.

        DurableTaskLeaseStore keeps validation and application inside its store
        critical section, eliminating the local validate-then-apply TOCTOU gap.
        Backends with true cross-process transactions can implement the same
        ``commit_if_owner`` contract with a database/external coordinator.
        """
        commit_if_owner = getattr(self.lease_store, "commit_if_owner", None)
        if commit_if_owner is None:
            decision = self.validate(task_id, worker_id, lease_id)
            if not decision.accepted:
                raise PermissionError(decision.reason)
            return apply_result()
        return commit_if_owner(task_id, worker_id, lease_id, apply_result)
