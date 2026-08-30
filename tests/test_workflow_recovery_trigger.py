from datetime import datetime, timedelta, timezone

import pytest

from runtime.task import Task
from runtime.task_lease import TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_recovery_trigger import (
    RecoveryTriggerError,
    RecoveryTriggerState,
    WorkflowRecoveryTrigger,
)


NOW = datetime.now(timezone.utc)


def _task(status="running"):
    return Task("TASK-RECOVER", "recover", "test", "developer", status=status)


def _assessment(state=TaskLivenessState.STUCK):
    return StuckTaskAssessment("TASK-RECOVER", "worker-a", state, timedelta(seconds=31), timedelta(seconds=61))


def test_non_stuck_assessment_does_not_trigger():
    trigger = WorkflowRecoveryTrigger(FencedTaskLeaseManager())
    decision = trigger.evaluate(_task(), _assessment(TaskLivenessState.NO_PROGRESS))
    assert decision.state is RecoveryTriggerState.NOT_STUCK
    assert not decision.should_recover


def test_non_resumable_task_does_not_trigger():
    trigger = WorkflowRecoveryTrigger(FencedTaskLeaseManager())
    decision = trigger.evaluate(_task("completed"), _assessment())
    assert decision.state is RecoveryTriggerState.NOT_RESUMABLE


def test_live_lease_blocks_takeover():
    manager = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    manager.acquire("TASK-RECOVER", "worker-a", now=NOW)
    trigger = WorkflowRecoveryTrigger(manager)
    decision = trigger.evaluate(_task(), _assessment(), now=NOW)
    assert decision.state is RecoveryTriggerState.WAITING_FOR_LEASE_EXPIRY
    assert not decision.should_recover


def test_stuck_without_live_lease_triggers_recovery():
    trigger = WorkflowRecoveryTrigger(FencedTaskLeaseManager())
    decision = trigger.evaluate(_task(), _assessment())
    assert decision.state is RecoveryTriggerState.TRIGGERED
    assert decision.should_recover


def test_assessment_task_mismatch_is_rejected():
    trigger = WorkflowRecoveryTrigger(FencedTaskLeaseManager())
    assessment = StuckTaskAssessment("OTHER", "worker-a", TaskLivenessState.STUCK, timedelta(seconds=31), timedelta(seconds=61))
    with pytest.raises(RecoveryTriggerError):
        trigger.evaluate(_task(), assessment)


def test_trigger_does_not_mutate_task():
    task = _task()
    before = task.to_dict()
    WorkflowRecoveryTrigger(FencedTaskLeaseManager()).evaluate(task, _assessment())
    assert task.to_dict() == before
