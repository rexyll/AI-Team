from dataclasses import replace

from runtime.alert_delivery import AlertDelivery, AlertDeliveryManager, DeliveryStatus
from runtime.alerting import Alert, AlertSeverity


class Sink:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def deliver(self, delivery):
        self.calls.append(delivery.delivery_id)
        if self.fail:
            raise RuntimeError("sink unavailable")


def _delivery(delivery_id="DEL-001"):
    return AlertDelivery(
        delivery_id=delivery_id,
        alert=Alert("workflow.failure_rate", AlertSeverity.CRITICAL, "failure", "project-A"),
        status=DeliveryStatus.DELIVERED,
    )


def test_delivery_is_idempotent():
    sink = Sink()
    manager = AlertDeliveryManager(sink)
    first = manager.deliver(_delivery())
    second = manager.deliver(_delivery())
    assert first.status is DeliveryStatus.DELIVERED
    assert second.status is DeliveryStatus.DUPLICATE
    assert sink.calls == ["DEL-001"]


def test_failed_delivery_is_retryable():
    sink = Sink(fail=True)
    manager = AlertDeliveryManager(sink)
    result = manager.deliver(_delivery())
    assert result.status is DeliveryStatus.FAILED
    assert result.error == "RuntimeError"
    assert sink.calls == ["DEL-001"]


def test_empty_delivery_id_is_rejected():
    sink = Sink()
    manager = AlertDeliveryManager(sink)
    invalid = replace(_delivery(), delivery_id="")
    try:
        manager.deliver(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
