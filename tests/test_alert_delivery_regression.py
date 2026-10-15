from runtime.alert_delivery import AlertDelivery, AlertDeliveryManager, DeliveryStatus
from runtime.alert_delivery_observability import AlertDeliveryObserver
from runtime.alerting import Alert, AlertManager, AlertRule, AlertSeverity
from runtime.metrics import MetricsRegistry


class Sink:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []

    def deliver(self, delivery):
        self.calls.append(delivery.attempt)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary")


def _alert():
    return Alert("workflow.failure_rate", AlertSeverity.WARNING, "failure", "project-A")


def test_alert_dedup_then_delivery_idempotency_are_independent():
    clock = [0.0]
    manager = AlertManager(clock=lambda: clock[0])
    manager.register(AlertRule("r1", AlertSeverity.WARNING, "warning", lambda _: True, cooldown_seconds=60))
    first = manager.evaluate(object(), dedup_key="project-A")
    second = manager.evaluate(object(), dedup_key="project-A")
    assert len(first) == 1 and not second

    sink = Sink()
    delivery = AlertDeliveryManager(sink)
    d = AlertDelivery("D-1", first[0], DeliveryStatus.RETRYING)
    assert delivery.deliver(d).status is DeliveryStatus.DELIVERED
    assert delivery.deliver(d).status is DeliveryStatus.DUPLICATE
    assert sink.calls == [1]


def test_failed_delivery_does_not_emit_success_metric_and_retry_does():
    sink = Sink(failures=1)
    delivery = AlertDeliveryManager(sink, max_attempts=2)
    metrics = MetricsRegistry()
    observer = AlertDeliveryObserver(metrics)
    d = AlertDelivery("D-2", _alert(), DeliveryStatus.RETRYING)
    failed = delivery.deliver(d)
    observer.record(failed)
    succeeded = delivery.deliver(d)
    observer.record(succeeded)
    counters = metrics.snapshot()["counters"]
    assert counters["alert.delivery.failure_total"][0]["value"] == 1.0
    assert counters["alert.delivery.success_total"][0]["value"] == 1.0


def test_retry_exhaustion_is_bounded():
    sink = Sink(failures=10)
    delivery = AlertDeliveryManager(sink, max_attempts=2)
    d = AlertDelivery("D-3", _alert(), DeliveryStatus.RETRYING)
    assert delivery.deliver(d).status is DeliveryStatus.FAILED
    assert delivery.deliver(d).status is DeliveryStatus.FAILED
    result = delivery.deliver(d)
    assert result.error == "max_attempts_exceeded"
    assert sink.calls == [1, 2]
