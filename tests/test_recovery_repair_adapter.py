from runtime.failure_classification import FailureClass
from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.recovery_repair_adapter import RecoveryRepairAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager


def _manager() -> TaskManager:
    task = Task(
        id="TASK-REPAIR-001",
        title="repair",
        description="repair lifecycle",
        role="developer",
        status="reviewing",
    )
    return TaskManager([task])


def _intent() -> RecoveryIntent:
    return RecoveryIntent(
        action=RecoveryAction.REPAIR,
        task_id="TASK-REPAIR-001",
        failure_class=FailureClass.TEST,
        failure_reason="tests failed",
        decision_reason="implementation requires correction",
        attempt=0,
    )


def test_repair_uses_existing_reviewer_revision_transition():
    manager = _manager()
    RecoveryRepairAdapter(manager).apply(_intent())

    task = manager.get_task("TASK-REPAIR-001")
    assert task.status == "running"


def test_repair_adapter_does_not_create_a_new_task_status():
    manager = _manager()
    RecoveryRepairAdapter(manager).apply(_intent())

    assert manager.get_task("TASK-REPAIR-001").status == "running"


def test_repair_adapter_rejects_wrong_action():
    manager = _manager()
    intent = RecoveryIntent(
        action=RecoveryAction.REPLAN,
        task_id="TASK-REPAIR-001",
        failure_class=FailureClass.SPECIFICATION,
        failure_reason="requirements changed",
        decision_reason="replan required",
        attempt=0,
    )

    try:
        RecoveryRepairAdapter(manager).apply(intent)
    except ValueError as exc:
        assert "REPAIR" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_repair_adapter_requires_existing_reviewing_state():
    manager = TaskManager([
        Task(
            id="TASK-REPAIR-001",
            title="repair",
            description="repair lifecycle",
            role="developer",
            status="ready",
        )
    ])

    try:
        RecoveryRepairAdapter(manager).apply(_intent())
    except ValueError as exc:
        assert "reviewing" in str(exc)
    else:
        raise AssertionError("expected ValueError")
