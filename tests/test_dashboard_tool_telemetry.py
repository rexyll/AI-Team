from types import SimpleNamespace

from runtime.observability_dashboard import ObservabilityDashboard
from runtime.tracing import Tracer


def _task():
    return SimpleNamespace(id="TASK-TOOLS", title="tools", role="developer", status="completed", retry_history=[], review_round=0, status_history=[])


def test_dashboard_exposes_bounded_tool_loop_facts_from_trace_attributes():
    tracer = Tracer()
    with tracer.span("workflow.task", attributes={"task_id": "TASK-TOOLS"}):
        with tracer.span("tool.execute", attributes={
            "task_id": "TASK-TOOLS", "execution_id": "EXEC-1", "result_chars": 40,
        }):
            pass
        with tracer.span("tool.execute", attributes={
            "task_id": "TASK-TOOLS", "execution_id": "EXEC-2", "duplicate_of": "EXEC-1", "retry_of": "EXEC-1", "result_chars": 60,
        }):
            pass

    snapshot = ObservabilityDashboard(tracer=tracer).snapshot([_task()])
    assert len(snapshot.tool_calls) == 2
    assert snapshot.workflow.duplicate_tool_calls == 1
    assert snapshot.workflow.retry_tool_calls == 1
    assert snapshot.workflow.tool_result_chars == 100


def test_dashboard_tool_telemetry_does_not_copy_raw_tool_payloads():
    tracer = Tracer()
    secret = "TOP-SECRET-RAW-TOOL-RESULT"
    with tracer.span("workflow.task", attributes={"task_id": "TASK-TOOLS"}):
        with tracer.span("tool.execute", attributes={"task_id": "TASK-TOOLS", "result_chars": len(secret)}):
            pass

    snapshot = ObservabilityDashboard(tracer=tracer).snapshot([_task()])
    assert secret not in repr(snapshot)
    assert snapshot.workflow.tool_result_chars == len(secret)
