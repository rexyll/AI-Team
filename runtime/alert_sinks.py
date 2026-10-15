from __future__ import annotations

import json
from typing import Callable

from runtime.alert_delivery import AlertDelivery


def alert_event(delivery: AlertDelivery) -> dict[str, object]:
    """Build a bounded, JSON-safe event; never include raw tool/model payloads."""
    return {
        "event": "alert.delivery",
        "delivery_id": delivery.delivery_id,
        "status": delivery.status.value,
        "rule_id": delivery.alert.rule_id,
        "severity": delivery.alert.severity.value,
        "message": delivery.alert.message,
        "dedup_key": delivery.alert.dedup_key,
    }


class StructuredLogAlertSink:
    """Adapt structured event emission to the existing logger boundary."""

    def __init__(self, emit: Callable[[dict[str, object]], None]) -> None:
        self._emit = emit

    def deliver(self, delivery: AlertDelivery) -> None:
        event = alert_event(delivery)
        json.dumps(event, ensure_ascii=False, sort_keys=True)
        self._emit(event)
