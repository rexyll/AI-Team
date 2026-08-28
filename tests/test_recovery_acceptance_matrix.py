from __future__ import annotations

from dataclasses import replace

import pytest

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.failure_classification import FailureClass, classify_failure
from runtime.failure_recovery_executor import FailureRecoveryExecutor
from runtime.failure_recovery_policy import RecoveryAction, decide_recovery
from runtime.recovery_repair_adapter import RecoveryRepairAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus


def _failed_task(*, max_retries: int = 1) -> Task:
    return Task(
        id="TASK-ACCEPT-001",
        title="acceptance",
        description="acceptance task",
        role="developer",
        status="failed",
        max_retries=max_retries,
        error="RuntimeError: transient",
    )


def _manager(task: Task) -> TaskManager:
    return TaskManager([task])


def test_recovery_policy_matrix_is_mutually_exclusive():
    cases = [
        (FailureClass.TRANSIENT, 0, 1, RecoveryAction.RETRY),
        (FailureClass.TRANSIENT, 1, 1, RecoveryAction.BLOCK),
        (FailureClass.SPECIFICATION, 0, 1, RecoveryAction.REPLAN),
        (FailureClass.TOOL, 0, 1, RecoveryAction.RETRY),
        (FailureClass.DEPENDENCY, 0, 1, RecoveryAction.RETRY),
    ]
    for failure_class, retry_attempt, max_retries, expected in cases:
        decision = decide_recovery(
            classify_failure(failure_class=failure_class, reason="acceptance"),
            retry_attempt=retry_attempt,
            max_retries=max_retries,
        )
        assert decision.action is expected


def test_retry_acceptance_preserves_failure_provenance():
    task = _failed_task()
    manager = _manager(task)
    executor = FailureRecoveryExecutor(manager)
    decision = decide_recovery(
        classify_failure(failure_class=FailureClass.TRANSIENT, reason="network reset"),
        retry_attempt=task.retry_attempt,
        max_retries=task.max_retries,
    )

    executor.execute(task.id, decision)
    live = manager.get_task(task.id)
    assert live.status == "ready"
    assert live.retry_attempt == 1
    assert live.retry_history[-1]["reason"] == "network reset"


def test_block_acceptance_does_not_mutate_task_without_explicit_execution():
    task = _failed_task(max_retries=0)
    manager = _manager(task)
    decision = decide_recovery(
        classify_failure(failure_class=FailureClass.TRANSIENT, reason="exhausted"),
        retry_attempt=task.retry_attempt,
        max_retries=task.max_retries,
    )
    assert decision.action is RecoveryAction.BLOCK
    assert manager.get_task(task.id).status == "failed"


def test_repair_adapter_rejects_non_review_lifecycle_without_mutation():
    task = _failed_task(max_retries=0)
    manager = _manager(task)
    adapter = RecoveryRepairAdapter(manager)
    with pytest.raises(ValueError):
        adapter.apply(task.id, "repair")
    assert manager.get_task(task.id).status == "failed"


def test_second_failure_after_retry_exhaustion_blocks():
    task = _failed_task(max_retries=1)
    manager = _manager(task)
    executor = FailureRecoveryExecutor(manager)
    first = decide_recovery(
        classify_failure(failure_class=FailureClass.TRANSIENT, reason="first"),
        retry_attempt=0,
        max_retries=1,
    )
    executor.execute(task.id, first)
    live = manager.get_task(task.id)
    assert live.status == "ready"
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "second failure")

    second = decide_recovery(
        classify_failure(failure_class=FailureClass.TRANSIENT, reason="second"),
        retry_attempt=live.retry_attempt,
        max_retries=live.max_retries,
    )
    assert second.action is RecoveryAction.BLOCK
    assert live.retry_attempt == 1
