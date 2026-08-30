from runtime.metrics import MetricsRegistry
from runtime.structured_logging import StructuredLogger
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


class NullLogger:
    def info(self, event, *, fields=None):
        return {"event": event, "fields": dict(fields or {})}


def _event(event_id="EV-001"):
    return WorkflowEvent(
        event_id=event_id,
        event_type="task.completed",
        project_id="PROJECT-001",
        occurred_at="2026-08-30T00:00:00Z",
        task_id="TASK-001",
        payload={},
    )


def test_contextual_workflow_metric_contains_query_dimensions_without_trace_identity():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(logger=NullLogger(), metrics=metrics)

    log.append(_event())

    series = metrics.snapshot()["counters"]["workflow.events.contextual_total"]
    assert series == [
        {
            "labels": {
                "event_type": "task.completed",
                "operation": "append",
                "outcome": "appended",
                "project_id": "PROJECT-001",
                "task_id": "TASK-001",
            },
            "value": 1.0,
        }
    ]
    labels = series[0]["labels"]
    assert "trace_id" not in labels
    assert "span_id" not in labels


def test_contextual_metric_is_emitted_for_duplicate_and_conflict_outcomes():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(logger=NullLogger(), metrics=metrics)
    event = _event()
    log.append(event)
    assert log.append_if_absent(event) is False

    try:
        log.append_if_absent(_event(event_id="EV-001"))
    except ValueError:
        pass

    outcomes = {
        item["labels"]["outcome"]: item["value"]
        for item in metrics.snapshot()["counters"]["workflow.events.contextual_total"]
    }
    assert outcomes["appended"] == 1.0
    assert outcomes["duplicate"] == 1.0


def test_event_logger_and_contextual_metric_share_project_and_task_dimensions():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(logger=StructuredLogger(), metrics=metrics)
    event = _event()

    record = log._logger.info(
        "workflow.event.test",
        fields={"project_id": event.project_id, "task_id": event.task_id},
    )
    log.append(event)

    labels = metrics.snapshot()["counters"]["workflow.events.contextual_total"][0]["labels"]
    assert record["fields"]["project_id"] == labels["project_id"]
    assert record["fields"]["task_id"] == labels["task_id"]
