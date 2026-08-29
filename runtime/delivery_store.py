from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Literal

from runtime.process_lock import exclusive_process_lock


DeliveryStatus = Literal["processing", "committed"]


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

    A delivery key is reserved durably before the external mutation callback is
    invoked. A committed record survives a new process/store instance, so a
    retry can distinguish an already-completed delivery from a first delivery.

    ``processing`` is intentionally observable: a crash after the external
    mutation but before ``complete`` cannot be falsely claimed to be exactly
    once by this generic filesystem adapter. Exactly-once *effect* requires the
    mutation and delivery record to share one transactional/idempotent boundary.
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
        return self.root / f".delivery-{key.replace('/', '_').replace(chr(92), '_')}.lock"

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

    def commit(self, key: str, apply_result: Callable[[], object]) -> object:
        """Reference idempotent delivery operation.

        The delivery record is persisted before the callback and completed only
        after it succeeds. A crash in between leaves ``processing`` for explicit
        recovery rather than silently pretending that exactly-once was achieved.
        """
        decision = self.begin(key)
        if decision.duplicate:
            return None
        result = apply_result()
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
