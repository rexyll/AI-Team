from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_status import TaskStatus
from runtime.workflow import StageOutcome, TaskWorkflow, WorkflowStage
from runtime.workflow_transition import (
    WorkflowOutcomeKind,
    get_workflow_transition,
)


class _Agent:
    def __init__(self, role: str):
        self.role = role

    def run(self, task):
        raise AssertionError("stage execution is not part of this contract test")


def _workflow(status: TaskStatus) -> tuple[TaskManager, TaskWorkflow, Task]:
    task = Task(
        id="WF-INTEGRATION-001",
        title="workflow transition integration",
        description="verify TaskWorkflow stage transitions",
        role="developer",
        status=status.value,
    )
    manager = TaskManager([task])
    developer = _Agent("developer")
    tester = _Agent("tester")
    reviewer = _Agent("reviewer")
    router = AgentRouter()
    router.register("developer", developer)
    router.register("tester", tester)
    router.register("reviewer", reviewer)

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
    )
    return manager, workflow, task


def _result(status: str) -> AgentResult:
    return AgentResult(
        status=status,
        agent="contract-test",
        task_id="WF-INTEGRATION-001",
        message=status,
        data={},
    )


def _assert_transition(
    task: Task,
    stage: str,
    outcome: WorkflowOutcomeKind,
    history_index: int = -1,
) -> None:
    transition = get_workflow_transition(stage, outcome)
    assert task.status_history[history_index] == {
        "from": transition.source.value,
        "to": transition.target.value,
    }


def test_developer_success_uses_declared_transition():
    manager, workflow, task = _workflow(TaskStatus.RUNNING)

    workflow._apply_developer_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.DEVELOPER,
            status="completed",
            result=_result("completed"),
        ),
    )

    assert task.status == TaskStatus.REVIEW_PENDING.value
    _assert_transition(
        task,
        "developer",
        WorkflowOutcomeKind.SUCCESS,
    )


def test_developer_invalid_result_uses_declared_failure_transition():
    manager, workflow, task = _workflow(TaskStatus.RUNNING)

    workflow._apply_developer_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.DEVELOPER,
            status="invalid",
            result=_result("invalid"),
        ),
    )

    assert task.status == TaskStatus.FAILED.value
    _assert_transition(
        task,
        "developer",
        WorkflowOutcomeKind.INVALID_RESULT,
    )


def test_tester_success_uses_declared_transition():
    manager, workflow, task = _workflow(TaskStatus.REVIEW_PENDING)

    workflow._apply_tester_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.TESTER,
            status="passed",
            result=_result("passed"),
        ),
    )

    # Reviewer entry is a separate lifecycle transition performed by
    # TaskWorkflow immediately before reviewer execution.
    _assert_transition(
        task,
        "tester",
        WorkflowOutcomeKind.SUCCESS,
    )
    manager.mark_reviewing(task.id)
    assert task.status == TaskStatus.REVIEWING.value


def test_tester_quality_failure_uses_declared_revision_transition():
    manager, workflow, task = _workflow(TaskStatus.REVIEW_PENDING)

    workflow._apply_tester_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.TESTER,
            status="failed",
            result=_result("failed"),
        ),
    )

    assert task.status == TaskStatus.RUNNING.value
    _assert_transition(
        task,
        "tester",
        WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
    )


def test_reviewer_success_uses_declared_completion_transition():
    manager, workflow, task = _workflow(TaskStatus.REVIEWING)

    action = workflow._apply_reviewer_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.REVIEWER,
            status="approved",
            result=_result("approved"),
        ),
    )

    assert action == "completed"
    assert task.status == TaskStatus.COMPLETED.value
    _assert_transition(
        task,
        "reviewer",
        WorkflowOutcomeKind.SUCCESS,
    )


def test_reviewer_revision_uses_declared_quality_failure_transition():
    manager, workflow, task = _workflow(TaskStatus.REVIEWING)

    action = workflow._apply_reviewer_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.REVIEWER,
            status="revision",
            result=_result("revision"),
        ),
    )

    assert action == "revision"
    assert task.status == TaskStatus.RUNNING.value
    _assert_transition(
        task,
        "reviewer",
        WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
    )


def test_reviewer_invalid_result_uses_declared_failure_transition():
    manager, workflow, task = _workflow(TaskStatus.REVIEWING)

    action = workflow._apply_reviewer_outcome(
        task,
        StageOutcome(
            stage=WorkflowStage.REVIEWER,
            status="invalid",
            result=_result("invalid"),
        ),
    )

    assert action == "failed"
    assert task.status == TaskStatus.FAILED.value
    _assert_transition(
        task,
        "reviewer",
        WorkflowOutcomeKind.INVALID_RESULT,
    )
