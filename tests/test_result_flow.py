from copy import deepcopy

from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class ResultFlowDeveloper:
    def __init__(self):
        self.received_contexts = []

    def run(self, task):
        self.received_contexts.append(
            deepcopy(task.context)
        )

        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "Developer completed implementation",
            "result": {
                "files": [
                    "database.py",
                    "service.py",
                ],
                "implementation": "SQLite DAO implementation",
            },
        }


class ResultFlowTester:
    def __init__(self):
        self.received_contexts = []

    def run(self, task):
        self.received_contexts.append(
            deepcopy(task.context)
        )

        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "All tests passed",
            "result": {
                "passed": 10,
                "failed": 0,
                "coverage": 0.95,
            },
        }


class ResultFlowReviewer:
    def __init__(self):
        self.received_contexts = []

    def run(self, task):
        self.received_contexts.append(
            deepcopy(task.context)
        )

        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "Implementation approved",
            "result": {
                "approved": True,
                "comments": "Implementation quality is acceptable",
            },
        }


def create_result_flow_environment():
    task = Task(
        id="TASK-001",
        title="实现数据库模块",
        description="实现 SQLite DAO 数据访问层",
        role="developer",
        status="ready",
    )

    task_manager = TaskManager(
        [task]
    )

    developer = ResultFlowDeveloper()
    tester = ResultFlowTester()
    reviewer = ResultFlowReviewer()

    router = AgentRouter()

    router.register(
        "developer",
        developer,
    )

    router.register(
        "tester",
        tester,
    )

    router.register(
        "reviewer",
        reviewer,
    )

    workflow = TaskWorkflow(
        task_manager=task_manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
    )

    return (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    )


def test_developer_result_is_written_to_task():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert task.result

    assert (
        task.result["implementation"]
        == "SQLite DAO implementation"
    )

    assert (
        task.result["files"]
        == [
            "database.py",
            "service.py",
        ]
    )


def test_tester_receives_developer_result():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert tester.received_contexts

    context = tester.received_contexts[0]

    assert "dependencies" in context


def test_tester_result_is_written_to_task():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert task.test_result

    assert (
        task.test_result["passed"]
        == 10
    )

    assert (
        task.test_result["failed"]
        == 0
    )


def test_reviewer_receives_test_result():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert reviewer.received_contexts

    context = reviewer.received_contexts[0]

    assert (
        "tester_feedback" in context
    )


def test_reviewer_result_is_written_to_task():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert task.review_result

    assert (
        task.review_result["approved"]
        is True
    )


def test_all_agent_results_preserve_business_data():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert (
        task.result["implementation"]
        == "SQLite DAO implementation"
    )

    assert (
        task.test_result["coverage"]
        == 0.95
    )

    assert (
        task.review_result["comments"]
        == "Implementation quality is acceptable"
    )


def test_final_task_status_is_completed_after_approval():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert (
        task.status == "completed"
    )


def test_agent_execution_order_is_preserved():
    (
        task_manager,
        workflow,
        task,
        developer,
        tester,
        reviewer,
    ) = create_result_flow_environment()

    workflow.execute(task.id)

    assert len(
        developer.received_contexts
    ) == 1

    assert len(
        tester.received_contexts
    ) == 1

    assert len(
        reviewer.received_contexts
    ) == 1