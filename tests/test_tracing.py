import threading
import time

import pytest

from runtime.tracing import Tracer, get_current_span, get_current_trace_id


def test_nested_spans_share_trace_and_form_parent_child_lineage():
    tracer = Tracer()
    with tracer.span("workflow") as root:
        assert get_current_span() is root
        assert get_current_trace_id() == root.trace_id
        with tracer.span("task", attributes={"task_id": "TASK-001"}) as child:
            assert child.trace_id == root.trace_id
            assert child.parent_span_id == root.span_id
        assert get_current_span() is root
    assert get_current_span() is None

    records = tracer.snapshot()
    assert [item["name"] for item in records] == ["task", "workflow"]
    assert records[0]["trace_id"] == records[1]["trace_id"]
    assert records[0]["parent_span_id"] == records[1]["span_id"]
    assert records[0]["status"] == "ok"
    assert records[0]["duration_seconds"] >= 0


def test_span_exception_is_recorded_as_error_and_re_raised():
    tracer = Tracer()
    with pytest.raises(RuntimeError):
        with tracer.span("tool"):
            raise RuntimeError("boom")

    record = tracer.snapshot()[0]
    assert record["status"] == "error"
    assert record["error"] == "RuntimeError"
    assert record["ended_at"] is not None


def test_trace_attributes_are_redacted_and_snapshot_is_detached():
    tracer = Tracer()
    with tracer.span(
        "llm.call",
        attributes={"api_key": "secret", "authorization": "Bearer secret", "safe": "ok"},
    ):
        pass

    snapshot = tracer.snapshot()
    assert snapshot[0]["attributes"]["api_key"] == "[REDACTED]"
    assert snapshot[0]["attributes"]["authorization"] == "[REDACTED]"
    assert snapshot[0]["attributes"]["safe"] == "ok"
    snapshot[0]["attributes"]["safe"] = "changed"
    assert tracer.snapshot()[0]["attributes"]["safe"] == "ok"


def test_tracer_supports_explicit_parent_and_trace_id():
    tracer = Tracer()
    root = tracer.start_span("root", trace_id="trace-fixed")
    child = tracer.start_span("child", parent=root)
    assert child.trace_id == "trace-fixed"
    assert child.parent_span_id == root.span_id
    tracer.record(root)
    tracer.record(child)
    assert len(tracer.snapshot()) == 2


def test_tracing_is_context_local_across_threads():
    tracer = Tracer()
    seen = []
    with tracer.span("main"):
        seen.append(get_current_span().name)

        def worker():
            seen.append(get_current_span())
            with tracer.span("worker") as span:
                seen.append(span.parent_span_id)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert seen[0] == "main"
    assert seen[1] is None
    assert seen[2] is None


def test_invalid_names_and_attributes_are_rejected():
    tracer = Tracer()
    with pytest.raises(ValueError):
        tracer.start_span("")
    with pytest.raises(TypeError):
        tracer.start_span("x", attributes=[])
    with pytest.raises(TypeError):
        tracer.start_span("x", attributes={"bad": object()})
