from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Literal

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
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

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
                return DeliveryDecision(False, True, current.status)
            self._write(DeliveryRecord(key=key, status="processing"))
            return DeliveryDecision(True, False, "processing")

    def complete(self, key: str) -> DeliveryDecision:
        """Durably mark a previously reserved delivery as committed."""
        with exclusive_process_lock(self._lock_path(key)), self._lock:
            current = self._load(key)
            if current is None:
                raise ValueError("delivery must be begun before completion")
            if current.status == "committed":
                return DeliveryDecision(False, True, "committed")
            self._write(DeliveryRecord(key=key, status="committed"))
            return DeliveryDecision(True, False, "committed")

    def recover_processing(self, key: str, action: RecoveryAction) -> DeliveryDecision:
        """Resolve an interrupted delivery using an explicit reconciliation decision.

        ``commit`` is safe only when an authoritative sink/reconciliation check
        proves the external mutation already happened. ``retry`` is safe only
        when that check proves it did not happen. Neither decision is inferred
        from process liveness, timestamps, or the ``processing`` marker itself.
        """
        if action not in {"commit", "retry"}:
            raise ValueError("action must be 'commit' or 'retry'")
        with exclusive_process_lock(self._lock_path(key)), self._lock:
            current = self._load(key)
            if current is None:
                raise ValueError("delivery does not exist")
            if current.status == "committed":
                return DeliveryDecision(False, True, "committed")
            if action == "commit":
                self._write(DeliveryRecord(key=key, status="committed"))
                return DeliveryDecision(True, False, "committed")
            self._path(key).unlink(missing_ok=True)
            return DeliveryDecision(True, False, None)

    def commit(self, key: str, apply_result: Callable[[], object]) -> object:
        """Reference idempotent delivery operation.

        A duplicate, including a pre-existing ``processing`` record, is never
        automatically replayed. An interrupted delivery must first be resolved
        by ``recover_processing`` after reconciling the external sink.
        """
        decision = self.begin(key)
        if decision.duplicate:
            return None
        try:
            result = apply_result()
        except Exception:
            # Keep processing durable: the caller/recovery coordinator must
            # decide whether the external side effect happened.
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
