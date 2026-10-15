import threading
import time

import pytest

from runtime.metrics import MetricsRegistry


def test_counter_and_gauge_are_label_aware_and_snapshot_is_detached():
    metrics = MetricsRegistry()
    assert metrics.inc("workflow.completed", labels={"stage": "reviewer"}) == 1
    assert metrics.inc("workflow.completed", 2, labels={"stage": "reviewer"}) == 3
    metrics.set_gauge("workflow.in_flight", 2, labels={"queue": "default"})

    snapshot = metrics.snapshot()
    assert snapshot["counters"]["workflow.completed"][0] == {
        "labels": {"stage": "reviewer"},
        "value": 3.0,
    }
    assert snapshot["gauges"]["workflow.in_flight"][0]["value"] == 2.0
    snapshot["counters"]["workflow.completed"][0]["value"] = 99
    assert metrics.snapshot()["counters"]["workflow.completed"][0]["value"] == 3.0


def test_histogram_and_timer_capture_summary_statistics():
    metrics = MetricsRegistry()
    metrics.observe("llm.latency", 1.0)
    metrics.observe("llm.latency", 3.0)
    with metrics.time("workflow.duration"):
        time.sleep(0.001)

    snapshot = metrics.snapshot()
    histogram = snapshot["histograms"]["llm.latency"][0]
    assert histogram["count"] == 2
    assert histogram["sum"] == 4.0
    assert histogram["min"] == 1.0
    assert histogram["max"] == 3.0
    assert snapshot["histograms"]["workflow.duration"][0]["count"] == 1


def test_metrics_are_safe_for_concurrent_counter_updates():
    metrics = MetricsRegistry()

    def worker():
        for _ in range(1000):
            metrics.inc("events.total")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert metrics.snapshot()["counters"]["events.total"][0]["value"] == 8000.0


def test_metric_inputs_reject_invalid_names_labels_and_counter_decrements():
    metrics = MetricsRegistry()
    with pytest.raises(ValueError):
        metrics.inc("")
    with pytest.raises(ValueError):
        metrics.inc("events", -1)
    with pytest.raises(ValueError):
        metrics.inc("events", labels={"": "bad"})
    with pytest.raises(TypeError):
        metrics.inc("events", labels=[])
