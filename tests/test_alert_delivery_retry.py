from runtime.alert_delivery import AlertDelivery, AlertDeliveryManager, DeliveryStatus
from runtime.alerting import Alert, AlertSeverity


class FlakySink:
    def __init__(self, failures):
        self.failures = failures
        self.calls = []

    def deliver(self, delivery):
        self.calls.append(delivery.attempt)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary")


def _delivery():
    return AlertDelivery("DEL-RETRY", Alert("workflow.failure_rate", AlertSeverity.WARNING, "warning", "project-A"), DeliveryStatus.RETRYING)


def test_failed_delivery_can_be_retried_with_bounded_attempts():
    sink = FlakySink(2)
    manager = AlertDeliveryManager(sink, max_attempts=3)
    assert manager.deliver(_delivery()).status is DeliveryStatus.FAILED
    assert manager.deliver(_delivery()).status is DeliveryStatus.FAILED
    result = manager.deliver(_delivery())
    assert result.status is DeliveryStatus.DELIVERED
    assert sink.calls == [1, 2, 3]


def test_retry_after_success_is_suppressed_as_duplicate():
    sink = FlakySink(0)
    manager = AlertDeliveryManager(sink, max_attempts=2)
    assert manager.deliver(_delivery()).status is DeliveryStatus.DELIVERED
    assert manager.deliver(_delivery()).status is DeliveryStatus.DUPLICATE
    assert sink.calls == [1]
