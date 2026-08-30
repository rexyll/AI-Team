import json
import logging

from runtime.metrics import DEFAULT_METRICS
from runtime.structured_logging import StructuredLogger, build_log_record
from runtime.tracing import DEFAULT_TRACER


def test_structured_log_correlates_with_active_trace():
    DEFAULT_TRACER.reset()
    logger = StructuredLogger(logging.getLogger("test.observability"))

    with DEFAULT_TRACER.span("workflow.task", attributes={"task_id": "TASK-001"}) as root:
        record = logger.info("task.started", fields={"task_id": "TASK-001"})
        with DEFAULT_TRACER.span("workflow.stage.developer") as child:
            child_record = build_log_record("stage.started")

    assert record["trace_id"] == root.trace_id
    assert record["span_id"] == root.span_id
    assert child_record["trace_id"] == root.trace_id
    assert child_record["span_id"] == child.span_id


def test_structured_log_without_trace_has_no_synthetic_trace_context():
    DEFAULT_TRACER.reset()
    record = build_log_record("task.completed", fields={"task_id": "TASK-001"})

    assert "trace_id" not in record
    assert "span_id" not in record
    json.dumps(record, ensure_ascii=False)


def test_metrics_use_low_cardinality_dimensions_not_trace_identity():
    DEFAULT_METRICS.reset()
    DEFAULT_METRICS.inc(
        "workflow.tasks.completed",
        labels={"project_id": "PROJECT-001", "task_id": "TASK-001", "role": "developer", "stage": "developer", "status": "completed"},
    )

    snapshot = DEFAULT_METRICS.snapshot()
    labels = snapshot["counters"]["workflow.tasks.completed"][0]["labels"]
    assert labels["task_id"] == "TASK-001"
    assert labels["project_id"] == "PROJECT-001"
    assert "trace_id" not in labels
    assert "span_id" not in labels
