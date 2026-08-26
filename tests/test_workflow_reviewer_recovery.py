from runtime.agent_router import AgentRouter
from runtime.agent_result import AgentResult
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class _Developer:
    role = "developer"

    def run(self, task):
        return AgentResult(
            status="completed",
            agent="developer",
            task_id=task.id,
            message="implementation complete",
        )


class _Reviewer:
    role = "reviewer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1
        if self.calls == 1:
            return AgentResult(
                status="revision",
                agent="reviewer",
                task_id=task.id,
                message="REVISION_REQUIRED",
                data={
                    "reviewer_execution": {
                        "source": "recovery",
                        "recovered": False,
                        "primary_error": "primary unavailable",
                        "fallback_error": "fallback unavailable",
                    }
                },
            )
        return AgentResult(
            status="approved",
            agent="reviewer",
            task_id=task.id,
            message="APPROVED",
        )


def test_reviewer_recovery_retries_quality_gate_without_failing_task():
    task = Task(
        id="TASK-RECOVERY-001",
        title="Reviewer recovery",
        description="Reviewer infrastructure failure should recover",
        role="developer",
        status="ready",
    )
    manager = TaskManager([task])
    developer = _Developer()
    reviewer = _Reviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        max_review_rounds=1,
        max_reviewer_recovery_attempts=1,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"
    assert reviewer.calls == 2
    assert task.error is None
