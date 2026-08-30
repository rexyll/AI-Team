from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog


class RecordingLogger:
    def __init__(self):
        self.calls = []

    def info(self, event, *, fields=None):
        self.calls.append((event, dict(fields or {})))
        return {"event": event, "fields": dict(fields or {})}


def _event(event_id="EV-001", event_type="task.completed"):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id="PROJECT-001",
        occurred_at="2026-08-30T00:00:00Z",
        task_id="TASK-001",
        payload={"message": "untrusted payload"},
    )


def test_append_emits_structured_event_metadata_without_payload():
    logger = RecordingLogger()
    WorkflowEventLog(logger=logger).append(_event())

    assert len(logger.calls) == 1
    event, fields = logger.calls[0]
    assert event == "workflow.event.appended"
    assert fields == {
        "event_id": "EV-001",
        "event_type": "task.completed",
        "project_id": "PROJECT-001",
        "task_id": "TASK-001",
        "operation": "append",
    }
    assert "untrusted payload" not in str(fields)


def test_duplicate_and_conflict_are_observable_without_event_payload():
    logger = RecordingLogger()
    log = WorkflowEventLog(logger=logger)
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

    assert [call[0] for call in logger.calls] == [
        "workflow.event.appended",
        "workflow.event.duplicate",
        "workflow.event.conflict",
    ]


def test_merge_emits_counts_and_preserves_existing_event_semantics():
    logger = RecordingLogger()
    log = WorkflowEventLog(logger=logger)
    events = [_event("EV-001"), _event("EV-002")]

    assert log.merge(events) == 2
    event, fields = logger.calls[-1]
    assert event == "workflow.event.merge.completed"
    assert fields["received_count"] == 2
    assert fields["committed_count"] == 2
    assert fields["event_id"] == "EV-001"
    assert len(log) == 2
