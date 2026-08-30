from runtime.alert_delivery import AlertDelivery, DeliveryStatus
from runtime.alert_sinks import StructuredLogAlertSink, alert_event
from runtime.alerting import Alert, AlertSeverity


def _delivery():
    return AlertDelivery(
        delivery_id="DEL-001",
        alert=Alert("workflow.failure_rate", AlertSeverity.CRITICAL, "failure rate high", "project-A"),
        status=DeliveryStatus.DELIVERED,
    )


def test_alert_event_is_bounded_and_json_safe():
    event = alert_event(_delivery())
    assert event == {
        "event": "alert.delivery",
        "delivery_id": "DEL-001",
        "status": "delivered",
        "rule_id": "workflow.failure_rate",
        "severity": "critical",
        "message": "failure rate high",
        "dedup_key": "project-A",
    }


def test_structured_log_sink_emits_event_without_mutating_delivery():
    emitted = []
    sink = StructuredLogAlertSink(emitted.append)
    delivery = _delivery()
    sink.deliver(delivery)
    assert emitted == [alert_event(delivery)]
    assert delivery.status is DeliveryStatus.DELIVERED
