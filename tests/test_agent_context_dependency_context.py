from runtime.agent_context import AgentContext
from runtime.context_builder import ContextBuilder
from runtime.task import Task


def make_task(**kwargs):
    defaults = {
        "id": "TASK-002",
        "title": "developer task",
        "description": "implement feature",
        "role": "developer",
        "status": "running",
        "dependencies": ["TASK-001"],
    }
    defaults.update(kwargs)
    return Task(**defaults)


def test_agent_context_isolates_dependency_context():
    dependency_context = {
        "TASK-001": {
            "title": "architecture",
            "role": "architect",
            "result": {
                "architecture": {
                    "database": "SQLite",
                }
            },
        }
    }

    context = AgentContext(
        task_id="TASK-002",
        task_title="developer task",
        task_description="implement feature",
        role="developer",
        status="running",
        dependencies=["TASK-001"],
        dependency_context=dependency_context,
    )

    dependency_context["TASK-001"]["result"]["architecture"]["database"] = "PostgreSQL"

    assert context.dependency_context["TASK-001"]["result"]["architecture"] == {
        "database": "SQLite"
    }


def test_agent_context_dependency_context_round_trip():
    context = AgentContext(
        task_id="TASK-002",
        task_title="developer task",
        task_description="implement feature",
        role="developer",
        status="running",
        dependencies=["TASK-001"],
        dependency_context={
            "TASK-001": {
                "title": "architecture",
                "role": "architect",
                "result": {
                    "architecture": "SQLite",
                },
            }
        },
    )

    restored = AgentContext.from_dict(context.to_dict())

    assert restored.dependency_context == context.dependency_context


def test_context_builder_exposes_completed_dependency_snapshot():
    dependency = Task(
        id="TASK-001",
        title="architecture",
        description="design system",
        role="architect",
        status="completed",
        result={
            "architecture": "SQLite + repository",
        },
    )
    task = make_task()

    context = ContextBuilder({"TASK-001": dependency}).build_agent_context(task)

    assert context.dependencies == ["TASK-001"]
    assert context.dependency_context == {
        "TASK-001": {
            "title": "architecture",
            "role": "architect",
            "result": {
                "architecture": "SQLite + repository",
            },
        }
    }


def test_context_builder_uses_legacy_task_context_when_tasks_unavailable():
    task = make_task()
    task.context = {
        "TASK-001": {
            "title": "architecture",
            "role": "architect",
            "result": {
                "architecture": "SQLite + repository",
            },
        }
    }

    context = ContextBuilder({}).build_agent_context(task)

    assert context.dependencies == ["TASK-001"]
    assert context.dependency_context["TASK-001"]["result"] == {
        "architecture": "SQLite + repository",
    }
