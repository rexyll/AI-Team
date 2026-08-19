from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager


class MockDeveloper:
    role = "developer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "implemented",
        }


class MockReviewer:
    role = "reviewer"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED",
        }


class MockTester:
    role = "tester"

    def __init__(self):
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "TEST_PASSED",
        }

def test_orchestrator_routes_developer_through_review_workflow():
    task = Task(
        id="TASK-ORCH-001",
        title="orchestrator workflow",
        description="verify developer review path",
        role="developer",
        status="ready",
    )

    developer = MockDeveloper()
    reviewer = MockReviewer()
    tester = MockTester()
    
    router = AgentRouter()
    router.register("developer", developer)
    router.register("tester", tester)
    router.register("reviewer", reviewer)

    manager = TaskManager([task])
    orchestrator = Orchestrator(manager, router)

    orchestrator.run()

    assert task.status == "completed"
    assert developer.calls == 1
    assert reviewer.calls == 1
    assert tester.calls == 1
    assert task.test_result["status"] == "passed"
    assert task.review_result["status"] == "approved"


