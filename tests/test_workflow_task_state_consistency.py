import pytest

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_projection import WorkflowEventProjector


PROJECT_ID = "PROJECT-001"


def _event(event_id, event_type, task_id="TASK-001", second=0, payload=None):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=PROJECT_ID,
        task_id=task_id,
        occurred_at=f"2026-08-31T10:00:{second:02d}Z",
        payload=payload or {},
    )


def test_projection_matches_authoritative_task_through_real_workflow_event_names():
    task = Task("TASK-001", "build", "build it", "developer")
    manager = TaskManager([task])
    log = WorkflowEventLog()

    manager.mark_ready(task.id)
    log.append(_event("EVENT-001", "task_started", second=1, payload={"status": "running"}))
    manager.mark_running(task.id)

    manager.mark_developer_completed(task.id, {"status": "completed"})
    log.append(_event("EVENT-002", "developer_completed", second=2, payload={"status": "completed"}))

    manager.mark_reviewing(task.id)
    log.append(_event("EVENT-003", "tester_passed", second=3, payload={"status": "passed"}))
    log.append(_event("EVENT-004", "review_started", second=4, payload={"status": "reviewing"}))

    manager.mark_review_approved(task.id, {"status": "completed"})
    log.append(_event("EVENT-005", "reviewer_approved", second=5, payload={"status": "completed"}))

    projection = WorkflowEventProjector.assert_task_consistency(task, log, project_id=PROJECT_ID)

    assert projection.lifecycle_status == task.status == "completed"
    assert projection.review_status == "approved"


def test_retry_event_represents_ready_state_without_copying_retry_reason_into_task_error():
    task = Task("TASK-001", "retry", "retry it", "developer", max_retries=2)
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "temporary")
    manager.retry_task(task.id, reason="RuntimeError: temporary", retryable=True)

    log = WorkflowEventLog()
    log.merge(
        [
            _event("EVENT-001", "task_started", second=1, payload={"status": "running"}),
            _event("EVENT-002", "task_failed", second=2, payload={"status": "failed", "error": "temporary"}),
            _event(
                "EVENT-003",
                "task_retrying",
                second=3,
                payload={
                    "status": "ready",
                    "retry_attempt": 1,
                    "max_retries": 2,
                    "reason": "RuntimeError: temporary",
                },
            ),
        ]
    )

    projection = WorkflowEventProjector.assert_task_consistency(task, log, project_id=PROJECT_ID)

    assert projection.lifecycle_status == "ready"
    assert projection.retry_attempt == 1
    assert projection.max_retries == 2
    assert projection.error is None


def test_consistency_contract_rejects_divergent_authoritative_status():
    task = Task("TASK-001", "build", "build it", "developer")
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)

    log = WorkflowEventLog()
    log.append(_event("EVENT-001", "task_started", second=1, payload={"status": "running"}))

    manager.mark_developer_completed(task.id, {"status": "completed"})

    with pytest.raises(ValueError, match="workflow/task status mismatch.*TASK-001"):
        WorkflowEventProjector.assert_task_consistency(task, log, project_id=PROJECT_ID)


def test_bare_iterable_replay_uses_global_event_time_not_task_grouping():
    events = [
        _event("EVENT-003", "review_started", task_id="TASK-002", second=3, payload={"status": "reviewing"}),
        _event("EVENT-001", "task_started", task_id="TASK-001", second=1, payload={"status": "running"}),
        _event("EVENT-002", "task_started", task_id="TASK-002", second=2, payload={"status": "running"}),
    ]

    projection = WorkflowEventProjector.project(reversed(events), project_id=PROJECT_ID)

    assert projection.last_event_id == "EVENT-003"
    assert projection.last_event_type == "review_started"
    assert projection.task("TASK-001").last_event_id == "EVENT-001"
    assert projection.task("TASK-002").last_event_id == "EVENT-003"
