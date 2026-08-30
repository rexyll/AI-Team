from __future__ import annotations

from time import monotonic
from typing import Mapping

from runtime.alert_delivery import AlertDelivery, DeliveryStatus
from runtime.metrics import MetricsRegistry


class AlertDeliveryObserver:
    """Records low-cardinality delivery telemetry in the existing metrics boundary."""

    def __init__(self, metrics: MetricsRegistry) -> None:
        self._metrics = metrics

    def record(self, delivery: AlertDelivery, *, duration_seconds: float | None = None) -> None:
        labels: Mapping[str, object] = {
            "rule_id": delivery.alert.rule_id,
            "severity": delivery.alert.severity.value,
            "status": delivery.status.value,
        }
        self._metrics.inc("alert.delivery.attempts_total", labels=labels)
        if delivery.status is DeliveryStatus.DELIVERED:
            self._metrics.inc("alert.delivery.success_total", labels={"severity": delivery.alert.severity.value})
        elif delivery.status is DeliveryStatus.FAILED:
            self._metrics.inc("alert.delivery.failure_total", labels={"severity": delivery.alert.severity.value})
        elif delivery.status is DeliveryStatus.DUPLICATE:
            self._metrics.inc("alert.delivery.duplicate_total", labels={"severity": delivery.alert.severity.value})
        if duration_seconds is not None:
            self._metrics.observe("alert.delivery.duration_seconds", max(0.0, float(duration_seconds)), labels={"severity": delivery.alert.severity.value})


class TimedAlertDeliveryObserver:
    """Small helper for measuring one delivery operation without transport coupling."""

    def __init__(self, observer: AlertDeliveryObserver) -> None:
        self._observer = observer

    def record_operation(self, operation, delivery: AlertDelivery) -> AlertDelivery:
        started = monotonic()
        try:
            return operation()
        finally:
            self._observer.record(delivery, duration_seconds=monotonic() - started)
