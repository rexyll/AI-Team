from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Literal

from runtime.delivery_audit import DurableDeliveryAuditStore
from runtime.process_lock import exclusive_process_lock


DeliveryStatus = Literal["processing", "committed"]
RecoveryAction = Literal["commit", "retry"]


@dataclass(frozen=True)
class DeliveryRecord:
    key: str
    status: DeliveryStatus


@dataclass(frozen=True)
class DeliveryDecision:
    accepted: bool
    duplicate: bool
    status: DeliveryStatus | None


class DurableDeliveryStore:
    """Filesystem reference store for durable result-delivery identities.

    Execution is at-least-once. A delivery is durably reserved before its
    mutation callback and marked committed only after that callback succeeds.
    If a worker crashes after the mutation but before ``complete``, the record
    remains ``processing``. Recovery therefore requires an explicit, externally
    informed decision; the store never guesses whether an external side effect
    happened.

    When an audit store is supplied, every durable delivery decision is also
    recorded as an append-only audit event. Auditing is observational and does
    not change the delivery state machine.
    """

    def __init__(self, root: str | Path, *, audit_store: DurableDeliveryAuditStore | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.audit_store = audit_store

    def _audit(
        self,
        key: str,
        action: str,
        *,
        before: str | None = None,
        after: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self.audit_store is not None:
            self.audit_store.record(
                key,
                action,
                status_before=before,
                status_after=after,
                metadata=metadata,
            )

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("delivery key must be a non-empty string")
        safe = key.replace("/", "_").replace("\\", "_")
        return self.root / f"delivery-{safe}.json"

    def _lock_path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(chr(92), "_")
        return self.root / f".delivery-{safe}.lock"

    def status(self, key: str) -> DeliveryRecord | None:
        with exclusive_process_lock(self._lock_path(key)), self._lock:
            return self._load(key)

    def begin(self, key: str) -> DeliveryDecision:
        """Atomically reserve a delivery identity across processes."""
        with exclusive_process_lock(self._lock_path(key)), self._lock:
            current = self._load(key)
            if current is not None:
                self._audit(key, "duplicate", before=current.status, after=current.status)
                return DeliveryDecision(False, True, current.status)
            self._write(DeliveryRecord(key=key, status="processing"))
            self._audit(key, "begin", after="processing")
            return DeliveryDecision(True, False, "processing")

    def complete(self, key: str) -> DeliveryDecision:
        """Durably mark a previously reserved delivery as committed."""
        with exclusive_process_lock(self._lock_path(key)), self._lock:
            current = self._load(key)
            if current is None:
                raise ValueError("delivery must be begun before completion")
            if current.status == "committed":
                self._audit(key, "duplicate", before="committed", after="committed")
                return DeliveryDecision(False, True, "committed")
            self._write(DeliveryRecord(key=key, status="committed"))
            self._audit(key, "complete", before="processing", after="committed")
            return DeliveryDecision(True, False, "committed")

    def recover_processing(self, key: str, action: RecoveryAction) -> DeliveryDecision:
        """Resolve an interrupted delivery using an explicit reconciliation decision."""
        if action not in {"commit", "retry"}:
            raise ValueError("action must be 'commit' or 'retry'")
        with exclusive_process_lock(self._lock_path(key)), self._lock:
            current = self._load(key)
            if current is None:
                raise ValueError("delivery does not exist")
            if current.status == "committed":
                self._audit(key, "duplicate", before="committed", after="committed")
                return DeliveryDecision(False, True, "committed")
            if action == "commit":
                self._write(DeliveryRecord(key=key, status="committed"))
                self._audit(key, "recover_commit", before="processing", after="committed")
                return DeliveryDecision(True, False, "committed")
            self._path(key).unlink(missing_ok=True)
            self._audit(key, "recover_retry", before="processing", after=None)
            return DeliveryDecision(True, False, None)

    def commit(self, key: str, apply_result: Callable[[], object]) -> object:
        """Reference idempotent delivery operation."""
        decision = self.begin(key)
        if decision.duplicate:
            return None
        try:
            result = apply_result()
        except Exception:
            self._audit(key, "processing_after_error", before="processing", after="processing")
            raise
        self.complete(key)
        return result

    def _load(self, key: str) -> DeliveryRecord | None:
        path = self._path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        status = data.get("status")
        if status not in {"processing", "committed"} or data.get("key") != key:
            raise ValueError(f"Corrupt delivery record: {key}")
        return DeliveryRecord(key=key, status=status)

    def _write(self, record: DeliveryRecord) -> None:
        path = self._path(record.key)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps({"key": record.key, "status": record.status}, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
