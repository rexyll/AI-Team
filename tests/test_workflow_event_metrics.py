from runtime.metrics import MetricsRegistry
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


class NullLogger:
    def info(self, event, *, fields=None):
        return {"event": event, "fields": dict(fields or {})}


def _event(event_id="EV-001", event_type="task.completed"):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id="PROJECT-001",
        occurred_at="2026-08-30T00:00:00Z",
        task_id="TASK-001",
        payload={},
    )


def _series(snapshot, name):
    return snapshot["counters"][name]


def test_append_records_event_counter_and_size_gauge():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(logger=NullLogger(), metrics=metrics)

    log.append(_event())

    snapshot = metrics.snapshot()
    assert _series(snapshot, "workflow.events.total") == [
        {
            "labels": {
                "event_type": "task.completed",
                "operation": "append",
                "outcome": "appended",
            },
            "value": 1.0,
        }
    ]
    assert snapshot["gauges"]["workflow.event_log.size"][0]["value"] == 1.0


def test_duplicate_and_conflict_have_distinct_metric_outcomes():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(logger=NullLogger(), metrics=metrics)
    event = _event()
    log.append(event)
    assert log.append_if_absent(event) is False

    conflicting = _event(event_type="task.failed")
    try:
        log.append_if_absent(conflicting)
    except ValueError:
        pass
    else:
        raise AssertionError("expected event conflict")

    outcomes = {
        item["labels"]["outcome"]: item["value"]
        for item in _series(metrics.snapshot(), "workflow.events.total")
    }
    assert outcomes == {"appended": 1.0, "duplicate": 1.0, "conflict": 1.0}


def test_merge_records_each_committed_event_and_final_size():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(logger=NullLogger(), metrics=metrics)

    assert log.merge([_event("EV-001"), _event("EV-002")]) == 2

    snapshot = metrics.snapshot()
    counters = _series(snapshot, "workflow.events.total")
    assert counters == [
        {
            "labels": {
                "event_type": "task.completed",
                "operation": "merge",
                "outcome": "appended",
            },
            "value": 2.0,
        }
    ]
    assert snapshot["gauges"]["workflow.event_log.size"][0]["value"] == 2.0


def test_metrics_are_optional_and_do_not_change_event_log_contract():
    log = WorkflowEventLog(logger=NullLogger())
    event = _event()
    log.append(event)
    assert log.get("EV-001") == event
    assert len(log) == 1
