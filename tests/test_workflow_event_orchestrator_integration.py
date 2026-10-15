from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog
from core.orchestrator import Orchestrator


class FlakyDeveloper:
    role = "developer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


class Reviewer:
    role = "reviewer"

    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "approved",
        }


def test_orchestrator_emits_retry_lifecycle_events():
    task = Task(
        id="TASK-RETRY-001",
        title="retry event",
        description="exercise retry lifecycle events",
        role="developer",
        status="ready",
        max_retries=1,
    )
    manager = TaskManager([task])
    developer = FlakyDeveloper()
    reviewer = Reviewer()
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    log = WorkflowEventLog()

    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=router,
        workflow_event_log=log,
        project_id="PROJECT-RETRY-001",
    )
    orchestrator.run()

    assert task.status == "completed"
    assert task.retry_attempt == 1
    events = log.list_for_task(task.id)
    assert [event.event_type for event in events] == [
        "task_started",
        "task_failed",
        "task_retrying",
        "task_started",
        "developer_completed",
        "tester_skipped",
        "review_started",
        "reviewer_approved",
    ]
    execution_id = events[0].payload["execution_id"]
    assert isinstance(execution_id, str) and execution_id
    assert events[2].payload == {
        "status": "ready",
        "retry_attempt": 1,
        "max_retries": 1,
        "reason": "RuntimeError: temporary failure",
        "execution_id": execution_id,
    }
    assert all(
        event.payload.get("execution_id") == execution_id
        for event in events
    )
    assert events[-1].payload["status"] == "completed"
