from copy import deepcopy

from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class FakeDeveloper:
    def __init__(self):
        self.received_contexts = []
        self.received_tasks = []

    def run(self, task):
        self.received_tasks.append(task)
        self.received_contexts.append(
            deepcopy(task.context)
        )

        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "result": {
                "architecture": "SQLite DAO architecture",
                "implementation": "DAO implementation",
            },
        }


class FakeTester:
    def __init__(self):
        self.received_contexts = []
        self.received_tasks = []

    def run(self, task):
        self.received_tasks.append(task)
        self.received_contexts.append(
            deepcopy(task.context)
        )

        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "result": {
                "tests": "all tests passed",
            },
        }


class FakeReviewer:
    def __init__(self):
        self.received_contexts = []
        self.received_tasks = []

    def run(self, task):
        self.received_tasks.append(task)
        self.received_contexts.append(
            deepcopy(task.context)
        )

        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "result": {
                "review": "approved",
            },
        }


def create_context_test_environment():
    dependency = Task(
        id="TASK-001",
        title="数据库设计",
        description="设计 SQLite 数据库",
        role="architect",
        status="completed",
        result={
            "architecture": "SQLite DAO architecture",
        },
    )

    task = Task(
        id="TASK-002",
        title="数据库模块开发",
        description="实现数据库模块",
        role="developer",
        status="ready",
        dependencies=[
            "TASK-001",
        ],
    )

    task_manager = TaskManager(
        [
            dependency,
            task,
        ]
    )

    developer = FakeDeveloper()
    tester = FakeTester()
    reviewer = FakeReviewer()

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
        dependency,
        task,
        developer,
        tester,
        reviewer,
    )


def test_dependency_context_is_available_to_developer():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    workflow.execute(task.id)

    assert developer.received_contexts

    context = developer.received_contexts[0]

    assert "dependencies" in context

    dependencies = context["dependencies"]

    assert dependency.id in dependencies


def test_dependency_context_contains_completed_dependency_result():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    workflow.execute(task.id)

    context = developer.received_contexts[0]

    dependency_context = context[
        "dependencies"
    ][dependency.id]

    assert (
        dependency_context["title"]
        == dependency.title
    )

    assert (
        dependency_context["role"]
        == dependency.role
    )

    assert (
        dependency_context["result"]
        == dependency.result
    )


def test_developer_receives_context_before_execution():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    assert developer.received_contexts == []

    workflow.execute(task.id)

    assert len(
        developer.received_contexts
    ) == 1

    context = developer.received_contexts[0]

    assert (
        context["dependencies"][dependency.id][
            "result"
        ]
        == dependency.result
    )


def test_tester_receives_context_after_developer():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    workflow.execute(task.id)

    assert tester.received_contexts

    context = tester.received_contexts[0]

    assert "dependencies" in context

    assert (
        context["dependencies"][dependency.id][
            "result"
        ]
        == dependency.result
    )


def test_reviewer_receives_context_after_tester():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    workflow.execute(task.id)

    assert reviewer.received_contexts

    context = reviewer.received_contexts[0]

    assert "dependencies" in context

    assert (
        context["dependencies"][dependency.id][
            "result"
        ]
        == dependency.result
    )


def test_dependency_context_excludes_incomplete_dependency():
    incomplete_dependency = Task(
        id="TASK-001",
        title="数据库设计",
        description="设计 SQLite 数据库",
        role="architect",
        status="pending",
        result={
            "architecture": "SQLite DAO architecture",
        },
    )

    task = Task(
        id="TASK-002",
        title="数据库模块开发",
        description="实现数据库模块",
        role="developer",
        status="ready",
        dependencies=[
            "TASK-001",
        ],
    )

    task_manager = TaskManager(
        [
            incomplete_dependency,
            task,
        ]
    )

    developer = FakeDeveloper()
    tester = FakeTester()
    reviewer = FakeReviewer()

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

    workflow.execute(task.id)

    assert developer.received_contexts

    context = developer.received_contexts[0]

    assert (
        context["dependencies"] == {}
    )


def test_missing_dependency_is_not_added_to_context():
    task = Task(
        id="TASK-002",
        title="数据库模块开发",
        description="实现数据库模块",
        role="developer",
        status="ready",
        dependencies=[
            "TASK-999",
        ],
    )

    task_manager = TaskManager(
        [
            task,
        ]
    )

    developer = FakeDeveloper()
    tester = FakeTester()
    reviewer = FakeReviewer()

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

    workflow.execute(task.id)

    assert developer.received_contexts

    context = developer.received_contexts[0]

    assert (
        context["dependencies"] == {}
    )


def test_context_is_available_to_all_workflow_stages():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    workflow.execute(task.id)

    assert developer.received_contexts
    assert tester.received_contexts
    assert reviewer.received_contexts

    developer_context = (
        developer.received_contexts[0]
    )

    tester_context = (
        tester.received_contexts[0]
    )

    reviewer_context = (
        reviewer.received_contexts[0]
    )

    expected_dependency = (
        developer_context[
            "dependencies"
        ][dependency.id]
    )

    assert (
        tester_context["dependencies"][
            dependency.id
        ]
        == expected_dependency
    )

    assert (
        reviewer_context["dependencies"][
            dependency.id
        ]
        == expected_dependency
    )


def test_completed_dependency_context_is_read_only_snapshot():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    original_dependency_result = deepcopy(
        dependency.result
    )

    workflow.execute(task.id)

    assert developer.received_contexts

    context = developer.received_contexts[0]

    dependency_snapshot = (
        context["dependencies"][
            dependency.id
        ]
    )

    dependency_snapshot["result"][
        "architecture"
    ] = "MUTATED"

    assert (
        dependency.result
        == original_dependency_result
    )


def test_workflow_completes_with_context_enabled():
    (
        task_manager,
        workflow,
        dependency,
        task,
        developer,
        tester,
        reviewer,
    ) = create_context_test_environment()

    result = workflow.execute(task.id)

    assert result is task

    assert (
        task.status == "completed"
    )

    assert developer.received_contexts
    assert tester.received_contexts
    assert reviewer.received_contexts

    assert (
        task.result
    )