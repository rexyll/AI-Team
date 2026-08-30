from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.alert_delivery import AlertDelivery
from runtime.alert_sinks import alert_event
from security.network import NetworkPolicy


class WebhookAlertSink:
    """Deliver bounded alert events through the existing network policy."""

    def __init__(self, url: str, *, policy: NetworkPolicy, send: Callable[..., Any]) -> None:
        self._url = policy.validate_url(url)
        self._send = send

    def deliver(self, delivery: AlertDelivery) -> None:
        payload = alert_event(delivery)
        self._send(self._url, payload)
