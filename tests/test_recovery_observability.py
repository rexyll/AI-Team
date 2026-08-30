from datetime import datetime, timezone

from runtime.metrics import MetricsRegistry
from runtime.recovery_observability import RecoveryObservability
from runtime.workflow_event_log import WorkflowEventLog


def test_recovery_observability_emits_audit_event_and_metric():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(metrics=metrics)
    observer = RecoveryObservability(
        log,
        metrics=metrics,
        project_id="PROJECT-1",
        clock=lambda: datetime(2026, 8, 30, tzinfo=timezone.utc),
    )

    observation = observer.takeover("TASK-1", generation=7, reason="stuck task")

    assert observation.event_type == "workflow.recovery.takeover"
    event = log.get("RECOVERY-" + log.list_all()[0].event_id.removeprefix("RECOVERY-"))
    assert event.task_id == "TASK-1"
    assert event.project_id == "PROJECT-1"
    assert event.payload == {"outcome": "takeover", "reason": "stuck task", "generation": 7}

    values = metrics.snapshot()["counters"]["workflow.recovery.total"]
    assert {item["labels"]["event_type"] for item in values} == {"workflow.recovery.takeover"}


def test_recovery_observability_does_not_put_task_identity_in_metric_labels():
    metrics = MetricsRegistry()
    log = WorkflowEventLog(metrics=metrics)
    observer = RecoveryObservability(log, metrics=metrics, project_id="PROJECT-1")
    observer.completed("TASK-SECRET", generation=3)

    labels = metrics.snapshot()["counters"]["workflow.recovery.total"][0]["labels"]
    assert "task_id" not in labels
    assert "trace_id" not in labels
    assert "span_id" not in labels


def test_recovery_observability_rejects_unknown_outcome():
    metrics = MetricsRegistry()
    observer = RecoveryObservability(WorkflowEventLog(metrics=metrics), metrics=metrics)
    try:
        observer.emit("unknown", "TASK-1")
    except ValueError as exc:
        assert "unsupported recovery observation" in str(exc)
    else:
        raise AssertionError("expected ValueError")
