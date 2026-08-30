from datetime import datetime, timezone

import pytest

from runtime.metrics import MetricsRegistry
from runtime.recovery_observability import RecoveryObservability
from runtime.task import Task
from runtime.task_lease import TaskLeaseManager
from runtime.task_lease_fencing import FencedTaskLeaseManager
from runtime.task_liveness import TaskLiveness
from runtime.task_stuck import StuckTaskAssessment, TaskLivenessState
from runtime.workflow_checkpoint import WorkflowCheckpoint
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_recovery_runner import WorkflowRecoveryRunError, WorkflowRecoveryRunner

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _task():
    return Task("TASK-RECOVER", "recover", "resume", "developer", status="ready")


def _assessment():
    return StuckTaskAssessment("TASK-RECOVER", "old-worker", TaskLivenessState.STUCK, __import__("datetime").timedelta(seconds=31), __import__("datetime").timedelta(seconds=61))


class _Workflow:
    def __init__(self, task):
        self.task_manager = type("Manager", (), {"get_task": lambda self, task_id: task})()
        self.calls = 0

    def execute(self, task_id):
        self.calls += 1
        return self.task_manager.get_task(task_id)


def test_runner_emits_takeover_started_and_completed():
    task = _task()
    checkpoint = WorkflowCheckpoint.capture(task)
    leases = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    metrics = MetricsRegistry()
    log = WorkflowEventLog(metrics=metrics)
    observer = RecoveryObservability(log, metrics=metrics, project_id="PROJECT-1", clock=lambda: NOW)
    workflow = _Workflow(task)
    result = WorkflowRecoveryRunner(workflow, leases, observability=observer).restart(
        checkpoint, _assessment(), owner_id="worker-b", now=NOW
    )
    assert result.task.id == task.id
    assert workflow.calls == 1
    assert [event.event_type for event in log.list_all()] == [
        "workflow.recovery.takeover",
        "workflow.recovery.started",
        "workflow.recovery.completed",
    ]
    assert leases.get(task.id, now=NOW) is None


def test_runner_emits_failed_when_execution_raises():
    task = _task()
    checkpoint = WorkflowCheckpoint.capture(task)
    leases = FencedTaskLeaseManager(TaskLeaseManager(default_ttl_seconds=30))
    metrics = MetricsRegistry()
    log = WorkflowEventLog(metrics=metrics)
    observer = RecoveryObservability(log, metrics=metrics, project_id="PROJECT-1", clock=lambda: NOW)

    class FailingWorkflow(_Workflow):
        def execute(self, task_id):
            raise RuntimeError("boom")

    with pytest.raises(WorkflowRecoveryRunError):
        WorkflowRecoveryRunner(FailingWorkflow(task), leases, observability=observer).restart(
            checkpoint, _assessment(), owner_id="worker-b", now=NOW
        )
    assert [event.event_type for event in log.list_all()] == [
        "workflow.recovery.takeover",
        "workflow.recovery.started",
        "workflow.recovery.failed",
    ]
    assert leases.get(task.id, now=NOW) is None
