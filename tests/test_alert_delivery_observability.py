from runtime.alert_delivery import AlertDelivery, DeliveryStatus
from runtime.alert_delivery_observability import AlertDeliveryObserver, TimedAlertDeliveryObserver
from runtime.alerting import Alert, AlertSeverity
from runtime.metrics import MetricsRegistry


def _delivery(status):
    return AlertDelivery("DEL-OBS", Alert("workflow.failure_rate", AlertSeverity.WARNING, "warning", "project-A"), status, attempt=1)


def test_delivery_observer_records_status_with_low_cardinality_labels():
    metrics = MetricsRegistry()
    observer = AlertDeliveryObserver(metrics)
    observer.record(_delivery(DeliveryStatus.DELIVERED), duration_seconds=0.25)
    observer.record(_delivery(DeliveryStatus.FAILED))
    observer.record(_delivery(DeliveryStatus.DUPLICATE))
    snapshot = metrics.snapshot()
    assert sum(x["value"] for x in snapshot["counters"]["alert.delivery.attempts_total"]) == 3.0
    assert snapshot["counters"]["alert.delivery.success_total"][0]["value"] == 1.0
    assert snapshot["counters"]["alert.delivery.failure_total"][0]["value"] == 1.0
    assert snapshot["counters"]["alert.delivery.duplicate_total"][0]["value"] == 1.0
    assert snapshot["histograms"]["alert.delivery.duration_seconds"][0]["count"] == 1


def test_timed_observer_returns_operation_result():
    metrics = MetricsRegistry()
    observer = TimedAlertDeliveryObserver(AlertDeliveryObserver(metrics))
    expected = _delivery(DeliveryStatus.DELIVERED)
    result = observer.record_operation(lambda: expected, expected)
    assert result is expected
    assert metrics.snapshot()["counters"]["alert.delivery.success_total"][0]["value"] == 1.0
