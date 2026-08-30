from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Protocol

from runtime.alerting import Alert


class DeliveryStatus(str, Enum):
    DELIVERED = "delivered"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    RETRYING = "retrying"


@dataclass(frozen=True)
class AlertDelivery:
    delivery_id: str
    alert: Alert
    status: DeliveryStatus
    attempt: int = 0
    error: str | None = None


class AlertSink(Protocol):
    def deliver(self, delivery: AlertDelivery) -> None: ...


class AlertDeliveryManager:
    """Coordinates idempotent alert delivery and bounded retry state."""

    def __init__(self, sink: AlertSink, *, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._sink = sink
        self._max_attempts = max_attempts
        self._delivered: set[str] = set()
        self._attempts: dict[str, int] = {}
        self._lock = RLock()

    def deliver(self, delivery: AlertDelivery) -> AlertDelivery:
        if not delivery.delivery_id.strip():
            raise ValueError("delivery_id must be non-empty")
        with self._lock:
            if delivery.delivery_id in self._delivered:
                return AlertDelivery(delivery.delivery_id, delivery.alert, DeliveryStatus.DUPLICATE, self._attempts.get(delivery.delivery_id, 0))
            attempt = self._attempts.get(delivery.delivery_id, 0) + 1
            if attempt > self._max_attempts:
                return AlertDelivery(delivery.delivery_id, delivery.alert, DeliveryStatus.FAILED, attempt, "max_attempts_exceeded")
            self._attempts[delivery.delivery_id] = attempt
            try:
                self._sink.deliver(AlertDelivery(delivery.delivery_id, delivery.alert, DeliveryStatus.RETRYING, attempt))
            except Exception as exc:
                return AlertDelivery(delivery.delivery_id, delivery.alert, DeliveryStatus.FAILED, attempt, type(exc).__name__)
            self._delivered.add(delivery.delivery_id)
            return AlertDelivery(delivery.delivery_id, delivery.alert, DeliveryStatus.DELIVERED, attempt)

    def reset(self) -> None:
        with self._lock:
            self._delivered.clear()
            self._attempts.clear()
