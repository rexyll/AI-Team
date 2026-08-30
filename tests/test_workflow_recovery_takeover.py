from datetime import datetime, timedelta, timezone

import pytest

from runtime.task import Task
from runtime.task_lease import TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_recovery_takeover import RecoveryTakeoverError, WorkflowRecoveryTakeover

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _task(status="running"):
    return Task("TASK-TAKEOVER", "take over", "resume", "developer", status=status)


def _assessment():
    return StuckTaskAssessment(
        "TASK-TAKEOVER",
        "old-worker",
        TaskLivenessState.STUCK,
        timedelta(seconds=61),
        timedelta(seconds=121),
    )


def test_takeover_acquires_new_fenced_generation_after_stuck_lease_expires():
    manager = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    old = manager.acquire("TASK-TAKEOVER", "old-worker", now=NOW)
    takeover = WorkflowRecoveryTakeover(manager).takeover(
        WorkflowCheckpoint.capture(_task()), _assessment(), owner_id="new-worker", now=NOW + timedelta(seconds=31)
    )
    assert takeover.task.status == "running"
    assert takeover.lease.generation == old.generation + 1
    assert takeover.lease.lease.owner_id == "new-worker"


def test_takeover_rejects_non_stuck_or_non_resumable_checkpoint():
    manager = FencedTaskLeaseManager(default_ttl_seconds=30)
    checkpoint = WorkflowCheckpoint.capture(_task(status="completed"))
    assessment = StuckTaskAssessment("TASK-TAKEOVER", "old-worker", TaskLivenessState.STUCK, timedelta(61), timedelta(121))
    with pytest.raises(RecoveryTakeoverError):
        WorkflowRecoveryTakeover(manager).takeover(checkpoint, assessment, owner_id="new-worker", now=NOW)


def test_takeover_rejects_ownership_race_without_replaying_task():
    manager = FencedTaskLeaseManager(default_ttl_seconds=30)
    manager.acquire("TASK-TAKEOVER", "winner", now=NOW)
    checkpoint = WorkflowCheckpoint.capture(_task())
    with pytest.raises(RecoveryTakeoverError):
        WorkflowRecoveryTakeover(manager).takeover(checkpoint, _assessment(), owner_id="new-worker", now=NOW)
    assert checkpoint.restore().status == "running"
