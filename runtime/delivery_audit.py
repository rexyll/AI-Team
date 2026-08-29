from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from runtime.process_lock import exclusive_process_lock


@dataclass(frozen=True)
class DeliveryAuditEvent:
    event_id: str
    delivery_key: str
    action: str
    status_before: str | None
    status_after: str | None
    metadata: dict[str, Any]


class DurableDeliveryAuditStore:
    """Append-only durable audit log for delivery state transitions.

    Audit writes are serialized with an OS-level lock so independent workers
    cannot interleave records. The audit is observational: failure to write an
    audit record is surfaced to the caller rather than silently weakening the
    delivery semantics.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "delivery-audit.jsonl"
        self._lock_path = self.root / ".delivery-audit.lock"
        self._lock = RLock()

    def record(
        self,
        delivery_key: str,
        action: str,
        *,
        status_before: str | None = None,
        status_after: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DeliveryAuditEvent:
        if not isinstance(delivery_key, str) or not delivery_key.strip():
            raise ValueError("delivery key must be a non-empty string")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("audit action must be a non-empty string")
        payload = dict(metadata or {})
        event = DeliveryAuditEvent(
            event_id=uuid4().hex,
            delivery_key=delivery_key,
            action=action,
            status_before=status_before,
            status_after=status_after,
            metadata=payload,
        )
        with exclusive_process_lock(self._lock_path), self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "event_id": event.event_id,
                            "delivery_key": event.delivery_key,
                            "action": event.action,
                            "status_before": event.status_before,
                            "status_after": event.status_after,
                            "metadata": event.metadata,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
                handle.flush()
        return event

    def records(self, delivery_key: str | None = None) -> list[DeliveryAuditEvent]:
        with exclusive_process_lock(self._lock_path), self._lock:
            if not self._path.exists():
                return []
            events: list[DeliveryAuditEvent] = []
            for line in self._path.read_text(encoding="utf-8").splitlines():
                data = json.loads(line)
                event = DeliveryAuditEvent(
                    event_id=data["event_id"],
                    delivery_key=data["delivery_key"],
                    action=data["action"],
                    status_before=data.get("status_before"),
                    status_after=data.get("status_after"),
                    metadata=dict(data.get("metadata") or {}),
                )
                if delivery_key is None or event.delivery_key == delivery_key:
                    events.append(event)
            return events
