import pytest

from runtime.alert_delivery import AlertDelivery, DeliveryStatus
from runtime.webhook_alert_sink import WebhookAlertSink
from runtime.alerting import Alert, AlertSeverity
from security.network import NetworkPolicy


def _delivery():
    return AlertDelivery(
        delivery_id="DEL-001",
        alert=Alert("workflow.failure_rate", AlertSeverity.CRITICAL, "failure rate high", "project-A"),
        status=DeliveryStatus.DELIVERED,
    )


def test_webhook_sink_requires_https_and_authorized_host():
    calls = []
    policy = NetworkPolicy(allowed_hosts=frozenset({"alerts.example.com"}))
    sink = WebhookAlertSink("https://alerts.example.com/hook", policy=policy, send=lambda *args: calls.append(args))
    sink.deliver(_delivery())
    assert len(calls) == 1
    assert calls[0][0] == "https://alerts.example.com/hook"
    assert calls[0][1]["event"] == "alert.delivery"


def test_webhook_sink_rejects_http_before_transport():
    calls = []
    policy = NetworkPolicy(allowed_hosts=frozenset({"alerts.example.com"}))
    with pytest.raises(PermissionError):
        WebhookAlertSink("http://alerts.example.com/hook", policy=policy, send=lambda *args: calls.append(args))
    assert calls == []


def test_webhook_sink_rejects_unauthorized_host_before_transport():
    calls = []
    policy = NetworkPolicy(allowed_hosts=frozenset({"alerts.example.com"}))
    with pytest.raises(PermissionError):
        WebhookAlertSink("https://evil.example.net/hook", policy=policy, send=lambda *args: calls.append(args))
    assert calls == []
