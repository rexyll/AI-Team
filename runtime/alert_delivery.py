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


@dataclass(frozen=True)
class AlertDelivery:
    delivery_id: str
    alert: Alert
    status: DeliveryStatus
    error: str | None = None


class AlertSink(Protocol):
    def deliver(self, delivery: AlertDelivery) -> None: ...


class AlertDeliveryManager:
    """Coordinates idempotent alert delivery without choosing a transport."""

    def __init__(self, sink: AlertSink) -> None:
        self._sink = sink
        self._delivered: set[str] = set()
        self._lock = RLock()

    def deliver(self, delivery: AlertDelivery) -> AlertDelivery:
        if not delivery.delivery_id.strip():
            raise ValueError("delivery_id must be non-empty")
        with self._lock:
            if delivery.delivery_id in self._delivered:
                return AlertDelivery(
                    delivery_id=delivery.delivery_id,
                    alert=delivery.alert,
                    status=DeliveryStatus.DUPLICATE,
                )
            try:
                self._sink.deliver(delivery)
            except Exception as exc:
                return AlertDelivery(
                    delivery_id=delivery.delivery_id,
                    alert=delivery.alert,
                    status=DeliveryStatus.FAILED,
                    error=type(exc).__name__,
                )
            self._delivered.add(delivery.delivery_id)
            return AlertDelivery(
                delivery_id=delivery.delivery_id,
                alert=delivery.alert,
                status=DeliveryStatus.DELIVERED,
            )

    def reset(self) -> None:
        with self._lock:
            self._delivered.clear()
