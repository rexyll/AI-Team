from runtime.agent_router import AgentRouter
from runtime.failure_classification import FailureClass
from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.recovery_repair_adapter import RecoveryRepairAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class Developer:
    role = "developer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "repair implementation completed",
        }


class Reviewer:
    role = "reviewer"

    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED",
        }


def test_repair_intent_enters_existing_workflow_and_completes():
    task = Task(
        id="TASK-REPAIR-E2E-001",
        title="repair e2e",
        description="exercise recovery repair through the existing workflow",
        role="developer",
        status="reviewing",
    )
    manager = TaskManager([task])
    developer = Developer()
    reviewer = Reviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)

    intent = RecoveryIntent(
        action=RecoveryAction.REPAIR,
        task_id=task.id,
        failure_class=FailureClass.TEST,
        failure_reason="tests failed",
        decision_reason="implementation requires correction",
        attempt=0,
    )

    RecoveryRepairAdapter(manager).apply(intent)

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
    )
    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert result.review_round == 1
    assert developer.calls == 1
    assert reviewer.run is not None


def test_repair_does_not_bypass_existing_review_round_contract():
    task = Task(
        id="TASK-REPAIR-E2E-002",
        title="repair round",
        description="ensure repair reuses the normal review lifecycle",
        role="developer",
        status="reviewing",
    )
    manager = TaskManager([task])
    developer = Developer()
    reviewer = Reviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)

    RecoveryRepairAdapter(manager).apply(
        RecoveryIntent(
            action=RecoveryAction.REPAIR,
            task_id=task.id,
            failure_class=FailureClass.TEST,
            failure_reason="tests failed",
            decision_reason="implementation requires correction",
            attempt=0,
        )
    )

    result = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
    ).execute(task.id)

    assert result.status == "completed"
    assert result.review_round == 1
    assert result.status != "repairing"
