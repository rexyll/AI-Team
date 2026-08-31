from datetime import datetime, timedelta, timezone

import pytest

from runtime.task import Task
from runtime.task_lease import TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_manager import TaskManager
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_projection import WorkflowEventProjector
from runtime.workflow_recovery_runner import WorkflowRecoveryRunError, WorkflowRecoveryRunner
from runtime.workflow_recovery_takeover import RecoveryTakeoverError, WorkflowRecoveryTakeover


PROJECT_ID = "PROJECT-RECOVERY-CONSISTENCY"
TASK_ID = "TASK-RECOVERY-CONSISTENCY"
NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _task(status: str = "running") -> Task:
    return Task(
        TASK_ID,
        "recovery",
        "resume the recovered task",
        "developer",
        status=status,
        max_retries=2,
    )


def _event(event_id: str, event_type: str, second: int, payload: dict) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=PROJECT_ID,
        task_id=TASK_ID,
        occurred_at=f"2026-08-30T10:00:{second:02d}Z",
        payload=payload,
    )


def _assessment() -> StuckTaskAssessment:
    return StuckTaskAssessment(
        TASK_ID,
        "old-worker",
        TaskLivenessState.STUCK,
        timedelta(seconds=61),
        timedelta(seconds=121),
    )


def test_checkpoint_restore_matches_event_projection_for_resumable_state():
    task = _task("running")
    checkpoint = WorkflowCheckpoint.capture(task)
    log = WorkflowEventLog()
    log.append(_event("EVENT-001", "task_started", 1, {"status": "running"}))

    restored = checkpoint.restore()
    projection = WorkflowEventProjector.assert_task_consistency(
        restored,
        log,
        project_id=PROJECT_ID,
    )

    assert restored.to_dict() == task.to_dict()
    assert projection.lifecycle_status == "running"
    assert projection.error is None
    assert projection.retry_attempt == restored.retry_attempt == 0
    assert projection.max_retries == restored.max_retries == 2


def test_retry_checkpoint_replays_ready_state_and_clears_active_error():
    task = _task("pending")
    manager = TaskManager([task])
    manager.mark_ready(TASK_ID)
    manager.mark_running(TASK_ID)
    manager.mark_failed(TASK_ID, "temporary")
    manager.retry_task(TASK_ID, reason="temporary", retryable=True)
    checkpoint = WorkflowCheckpoint.capture(manager.get_task(TASK_ID))
    log = WorkflowEventLog()
    log.merge(
        [
            _event("EVENT-001", "task_started", 1, {"status": "running"}),
            _event("EVENT-002", "developer_failed", 2, {"status": "failed", "error": "temporary"}),
            _event(
                "EVENT-003",
                "task_retrying",
                3,
                {"status": "ready", "retry_attempt": 1, "max_retries": 2, "reason": "temporary"},
            ),
        ]
    )

    projection = WorkflowEventProjector.assert_task_consistency(
        checkpoint.restore(),
        log,
        project_id=PROJECT_ID,
    )

    assert projection.lifecycle_status == "ready"
    assert projection.error is None
    assert projection.retry_attempt == 1
    assert projection.max_retries == 2


def test_recovery_runner_rejects_task_manager_state_drift_before_execution_and_releases_lease():
    checkpoint_task = _task("running")
    checkpoint = WorkflowCheckpoint.capture(checkpoint_task)

    current_task = _task("ready")
    manager = TaskManager([current_task])
    calls = []

    class Workflow:
        task_manager = manager

        def execute(self, task_id):
            calls.append(task_id)
            return manager.get_task(task_id)

    leases = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    leases.acquire(TASK_ID, "old-worker", now=NOW)

    with pytest.raises(WorkflowRecoveryRunError, match="differs from checkpoint"):
        WorkflowRecoveryRunner(Workflow(), leases).restart(
            checkpoint,
            _assessment(),
            owner_id="new-worker",
            now=NOW + timedelta(seconds=31),
        )

    assert calls == []
    assert leases.get(TASK_ID, now=NOW + timedelta(seconds=31)) is None
    assert manager.get_task(TASK_ID).status == "ready"
    assert checkpoint.restore().status == "running"


def test_recovery_takeover_requires_resumable_checkpoint_before_lease_acquisition():
    leases = FencedTaskLeaseManager(default_ttl_seconds=30)
    completed = WorkflowCheckpoint.capture(_task("completed"))

    with pytest.raises(RecoveryTakeoverError, match="not_resumable"):
        WorkflowRecoveryTakeover(leases).takeover(
            completed,
            _assessment(),
            owner_id="new-worker",
            now=NOW,
        )

    assert leases.get(TASK_ID, now=NOW) is None
