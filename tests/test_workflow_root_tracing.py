from runtime.agent_router import AgentRouter
from runtime.agent_result import AgentResult
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tracing import DEFAULT_TRACER
from runtime.workflow import TaskWorkflow


class _Developer:
    role = "developer"

    def run(self, task):
        return AgentResult(
            status="completed",
            agent="developer",
            task_id=task.id,
            message="done",
        )


class _Reviewer:
    role = "reviewer"

    def run(self, task):
        return AgentResult(
            status="approved",
            agent="reviewer",
            task_id=task.id,
            message="APPROVED",
        )


def test_task_workflow_execute_creates_root_span_for_agent_stage_lineage():
    DEFAULT_TRACER.reset()
    task = Task(
        id="TASK-ROOT-TRACE",
        title="root tracing",
        description="verify workflow root span",
        role="developer",
        status="ready",
    )
    developer = _Developer()
    reviewer = _Reviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    workflow = TaskWorkflow(
        task_manager=TaskManager([task]),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
    )

    result = workflow.execute(task.id)

    assert result.status == "completed"
    records = DEFAULT_TRACER.snapshot()
    root = next(item for item in records if item["name"] == "workflow.task")
    stage = next(item for item in records if item["name"] == "workflow.stage.developer")
    assert root["parent_span_id"] is None
    assert root["attributes"]["task_id"] == task.id
    assert root["attributes"]["result.status"] == "completed"
    assert stage["parent_span_id"] == root["span_id"]
    assert stage["trace_id"] == root["trace_id"]
