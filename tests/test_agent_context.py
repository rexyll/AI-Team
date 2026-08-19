from runtime.context_builder import ContextBuilder
from runtime.task import Task


def test_context_builder_builds_agent_context():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
    )

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context["dependencies"] == {}
    assert context["tester_feedback"] is None
    assert context["reviewer_feedback"] is None


def test_context_contains_completed_dependency():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="developer",
        status="completed",
    )

    dependency.result = {
        "status": "completed",
        "agent": "developer",
        "task_id": "TASK-DEP-001",
        "message": "dependency completed",
    }

    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
        dependencies=["TASK-DEP-001"],
    )

    builder = ContextBuilder(
        {
            dependency.id: dependency,
        }
    )

    context = builder.build(task)

    assert "TASK-DEP-001" in context["dependencies"]

    dependency_context = context["dependencies"]["TASK-DEP-001"]

    assert dependency_context["title"] == "dependency"
    assert dependency_context["role"] == "developer"
    assert dependency_context["result"]["status"] == "completed"


def test_context_excludes_incomplete_dependency():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="developer",
        status="running",
    )

    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
        dependencies=["TASK-DEP-001"],
    )

    builder = ContextBuilder(
        {
            dependency.id: dependency,
        }
    )

    context = builder.build(task)

    assert context["dependencies"] == {}


def test_context_contains_tester_feedback():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
    )

    task.test_result = {
        "status": "failed",
        "agent": "tester",
        "task_id": "TASK-001",
        "message": "missing boundary tests",
    }

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context["tester_feedback"]["status"] == "failed"
    assert (
        context["tester_feedback"]["message"]
        == "missing boundary tests"
    )


def test_context_contains_reviewer_feedback():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="revision",
    )

    task.review_result = {
        "status": "revision",
        "agent": "reviewer",
        "task_id": "TASK-001",
        "message": "improve error handling",
    }

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context["reviewer_feedback"]["status"] == "revision"
    assert (
        context["reviewer_feedback"]["message"]
        == "improve error handling"
    )


def test_context_builder_does_not_mutate_task():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
    )

    task.test_result = {
        "status": "failed",
        "agent": "tester",
        "task_id": "TASK-001",
        "message": "missing boundary tests",
    }

    task.review_result = {
        "status": "revision",
        "agent": "reviewer",
        "task_id": "TASK-001",
        "message": "improve error handling",
    }

    original_status = task.status
    original_test_result = dict(task.test_result)
    original_review_result = dict(task.review_result)

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context is not None

    assert task.status == original_status
    assert task.test_result == original_test_result
    assert task.review_result == original_review_result


def test_legacy_build_task_context_api_still_works():
    from runtime.context_builder import build_task_context

    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
    )

    context = build_task_context(task, {})

    assert context["dependencies"] == {}
    assert context["tester_feedback"] is None
    assert context["reviewer_feedback"] is None