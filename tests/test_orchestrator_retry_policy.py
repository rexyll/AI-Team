from core.orchestrator import Orchestrator
from runtime.retry_policy import FailureKind
from runtime.task import Task
from runtime.task_manager import TaskManager


class FakeRouter:
    def get_agent(self, role):
        raise AssertionError("agent execution is not part of this contract test")


def test_retryable_execution_failure_requeues_failed_task():
    task = Task(id="ORCH-RETRY-001", title="retry", description="retry", role="architect")
    task.configure_retry(max_retries=1)
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "temporary failure")

    orchestrator = Orchestrator(manager, FakeRouter())
    assert orchestrator._apply_retry_policy(task, RuntimeError("temporary provider failure")) is True
    assert task.status == "ready"
    assert task.error is None
    assert task.retry_attempt == 1
    assert task.retry_history[0]["retryable"] is True
    assert task.status_history[-1] == {"from": "failed", "to": "ready"}


def test_non_retryable_failure_stays_failed():
    task = Task(id="ORCH-RETRY-002", title="retry", description="retry", role="architect")
    task.configure_retry(max_retries=3)
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "invalid configuration")

    orchestrator = Orchestrator(manager, FakeRouter())
    assert orchestrator._apply_retry_policy(task, ValueError("invalid configuration")) is False
    assert task.status == "failed"
    assert task.retry_attempt == 0
    assert task.retry_history == []
    assert task.error == "invalid configuration"


def test_retry_budget_exhaustion_stays_failed():
    task = Task(id="ORCH-RETRY-003", title="retry", description="retry", role="architect")
    task.configure_retry(max_retries=1)
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "first failure")

    orchestrator = Orchestrator(manager, FakeRouter())
    assert orchestrator._apply_retry_policy(task, RuntimeError("first failure")) is True

    manager.mark_running(task.id)
    manager.mark_failed(task.id, "second failure")
    assert orchestrator._apply_retry_policy(task, RuntimeError("second failure")) is False

    assert task.status == "failed"
    assert task.retry_attempt == 1
    assert len(task.retry_history) == 1
    assert task.error == "second failure"


def test_custom_failure_classifier_controls_retry_kind():
    task = Task(id="ORCH-RETRY-004", title="retry", description="retry", role="architect")
    task.configure_retry(max_retries=1)
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "quality gate")
    calls = []

    def classify(error):
        calls.append(error)
        return FailureKind.QUALITY_GATE

    orchestrator = Orchestrator(manager, FakeRouter(), failure_classifier=classify)
    assert orchestrator._apply_retry_policy(task, RuntimeError("quality gate")) is True
    assert calls
    assert task.retry_attempt == 1


def test_retry_policy_does_not_run_for_non_failed_task():
    task = Task(id="ORCH-RETRY-005", title="retry", description="retry", role="architect")
    task.configure_retry(max_retries=1)
    manager = TaskManager([task])
    orchestrator = Orchestrator(manager, FakeRouter())
    assert orchestrator._apply_retry_policy(task, RuntimeError("not failed")) is False
    assert task.status == "pending"
    assert task.retry_attempt == 0
