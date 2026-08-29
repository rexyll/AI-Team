from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable

from runtime.multi_process import TaskLease


@dataclass(frozen=True)
class ResultCommitDecision:
    accepted: bool
    reason: str


class ResultCommitFencer:
    """Reject late results unless the submitting worker owns the task lease.

    When a DurableDeliveryStore is supplied, delivery identities are also
    durably deduplicated. Execution remains at-least-once; the generic callback
    boundary is not claimed to be globally transactional.
    """

    def __init__(self, lease_store, delivery_store=None) -> None:
        self.lease_store = lease_store
        self.delivery_store = delivery_store

    @staticmethod
    def delivery_key(task_id: str, attempt: int, delivery_id: str) -> str:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        if not isinstance(delivery_id, str) or not delivery_id.strip():
            raise ValueError("delivery_id must be a non-empty string")
        return sha256(f"{task_id}\x00{attempt}\x00{delivery_id}".encode()).hexdigest()

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
        *,
        attempt: int | None = None,
        delivery_id: str | None = None,
    ) -> object:
        """Commit a result with ownership fencing and optional durable dedup.

        ``attempt`` + ``delivery_id`` must be supplied together. With durable
        delivery enabled, a repeated delivery returns ``None`` without running
        ``apply_result``. A ``processing`` record is deliberately retained
        across crashes; exactly-once effect requires the mutation and delivery
        record to participate in one transactional/idempotent boundary.
        """
        if (attempt is None) != (delivery_id is None):
            raise ValueError("attempt and delivery_id must be supplied together")

        commit_if_owner = getattr(self.lease_store, "commit_if_owner", None)
        if commit_if_owner is None:
            decision = self.validate(task_id, worker_id, lease_id)
            if not decision.accepted:
                raise PermissionError(decision.reason)

            def apply():
                return self._deliver(apply_result, attempt, delivery_id)

            return apply()

        return commit_if_owner(
            task_id,
            worker_id,
            lease_id,
            lambda: self._deliver(apply_result, attempt, delivery_id),
        )

    def _deliver(
        self,
        apply_result: Callable[[], object],
        attempt: int | None,
        delivery_id: str | None,
    ) -> object:
        if self.delivery_store is None or attempt is None or delivery_id is None:
            return apply_result()
        key = self.delivery_key("delivery", attempt, delivery_id)
        return self.delivery_store.commit(key, apply_result)
