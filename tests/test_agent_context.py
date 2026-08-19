from runtime.context_builder import build_task_context
from runtime.task import Task


def test_context_builder_builds_agent_context():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency task",
        description="dependency task",
        role="developer",
        status="completed",
        result={
            "status": "completed",
            "agent": "developer",
            "task_id": "TASK-DEP-001",
            "message": "dependency completed",
        },
    )

    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
        dependencies=["TASK-DEP-001"],
    )

    context = build_task_context(
        task,
        {
            dependency.id: dependency,
            task.id: task,
        },
    )

    assert "TASK-DEP-001" in context

    assert context["TASK-DEP-001"]["title"] == "dependency task"
    assert context["TASK-DEP-001"]["role"] == "developer"

    assert (
        context["TASK-DEP-001"]["result"]["message"]
        == "dependency completed"
    )


def test_context_builder_ignores_incomplete_dependency():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency task",
        description="dependency task",
        role="developer",
        status="running",
        result={
            "status": "completed",
            "message": "not actually completed",
        },
    )

    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
        dependencies=["TASK-DEP-001"],
    )

    context = build_task_context(
        task,
        {
            dependency.id: dependency,
            task.id: task,
        },
    )

    assert context == {}


def test_context_builder_ignores_missing_dependency():
    task = Task(
        id="TASK-001",
        title="demo",
        description="test task",
        role="developer",
        status="running",
        dependencies=["TASK-NOT-EXIST"],
    )

    context = build_task_context(
        task,
        {
            task.id: task,
        },
    )

    assert context == {}