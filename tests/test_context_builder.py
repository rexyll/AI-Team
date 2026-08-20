from copy import deepcopy

from runtime.context_builder import (
    ContextBuilder,
    build_task_context,
)
from runtime.task import Task


def make_task(**kwargs):
    defaults = {
        "id": "TASK-MAIN-001",
        "title": "main",
        "description": "main task",
        "role": "developer",
        "status": "running",
    }

    defaults.update(kwargs)

    return Task(**defaults)


def test_build_task_context_includes_completed_dependencies():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="developer",
        status="completed",
        result={
            "status": "completed",
            "message": "dependency done",
        },
    )

    task = make_task(
        dependencies=["TASK-DEP-001"],
    )

    context = build_task_context(
        task,
        {
            dependency.id: dependency,
            task.id: task,
        },
    )

    assert context["TASK-DEP-001"]["title"] == "dependency"
    assert context["TASK-DEP-001"]["role"] == "developer"
    assert (
        context["TASK-DEP-001"]["result"]["message"]
        == "dependency done"
    )


def test_build_task_context_ignores_incomplete_dependencies():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="developer",
        status="running",
        result={
            "status": "completed",
            "message": "not actually finished",
        },
    )

    task = make_task(
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


def test_build_task_context_ignores_missing_dependencies():
    task = make_task(
        dependencies=["TASK-NOT-EXIST"],
    )

    context = build_task_context(
        task,
        {
            task.id: task,
        },
    )

    assert context == {}


def test_context_builder_build_returns_expected_sections():
    task = make_task()

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context == {
        "dependencies": {},
        "tester_feedback": None,
        "reviewer_feedback": None,
    }


def test_context_builder_build_returns_tester_feedback():
    task = make_task()

    task.test_result = {
        "status": "failed",
        "message": "test failed",
    }

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context["tester_feedback"] == {
        "status": "failed",
        "message": "test failed",
    }


def test_context_builder_build_returns_reviewer_feedback():
    task = make_task()

    task.review_result = {
        "status": "revision",
        "message": "fix error handling",
    }

    builder = ContextBuilder({})

    context = builder.build(task)

    assert context["reviewer_feedback"] == {
        "status": "revision",
        "message": "fix error handling",
    }


def test_context_builder_returns_detached_dependency_result():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="architect",
        status="completed",
        result={
            "architecture": {
                "database": "SQLite",
            }
        },
    )

    task = make_task(
        dependencies=["TASK-DEP-001"],
    )

    builder = ContextBuilder(
        {
            dependency.id: dependency,
        }
    )

    context = builder.build(task)

    dependency.result["architecture"]["database"] = "PostgreSQL"

    assert (
        context["dependencies"]["TASK-DEP-001"]["result"]
        == {
            "architecture": {
                "database": "SQLite",
            }
        }
    )


def test_context_builder_returns_detached_tester_feedback():
    task = make_task()

    task.test_result = {
        "status": "failed",
        "details": {
            "count": 2,
        },
    }

    builder = ContextBuilder({})

    context = builder.build(task)

    task.test_result["details"]["count"] = 3

    assert context["tester_feedback"] == {
        "status": "failed",
        "details": {
            "count": 2,
        },
    }


def test_context_builder_returns_detached_reviewer_feedback():
    task = make_task()

    task.review_result = {
        "status": "revision",
        "details": {
            "count": 1,
        },
    }

    builder = ContextBuilder({})

    context = builder.build(task)

    task.review_result["details"]["count"] = 2

    assert context["reviewer_feedback"] == {
        "status": "revision",
        "details": {
            "count": 1,
        },
    }


def test_build_agent_context_returns_agent_context():
    task = make_task()

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.task_id == task.id
    assert context.task_title == task.title
    assert context.task_description == task.description
    assert context.role == task.role
    assert context.status == task.status


def test_build_agent_context_isolated_from_task_mutations():
    task = make_task(
        result={
            "implementation": {
                "files": ["main.py"],
            }
        }
    )

    task.test_result = {
        "status": "passed",
        "details": {
            "tests": 10,
        },
    }

    task.review_result = {
        "status": "approved",
        "details": {
            "issues": 0,
        },
    }

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    task.result["implementation"]["files"].append(
        "workflow.py"
    )
    task.test_result["details"]["tests"] = 20
    task.review_result["details"]["issues"] = 1

    assert context.task_result == {
        "implementation": {
            "files": ["main.py"],
        }
    }

    assert context.tester_feedback == {
        "status": "passed",
        "details": {
            "tests": 10,
        },
    }

    assert context.reviewer_feedback == {
        "status": "approved",
        "details": {
            "issues": 0,
        },
    }


def test_build_agent_context_contains_status_history():
    task = make_task()

    task.status_history = [
        {
            "from": "pending",
            "to": "running",
        }
    ]

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.history == [
        {
            "from": "pending",
            "to": "running",
        }
    ]


def test_build_agent_context_history_is_detached():
    task = make_task()

    task.status_history = [
        {
            "metadata": {
                "attempt": 1,
            }
        }
    ]

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    task.status_history[0]["metadata"]["attempt"] = 2

    assert context.history == [
        {
            "metadata": {
                "attempt": 1,
            }
        }
    ]


def test_build_agent_context_contains_non_core_metadata():
    task = make_task()

    task.context = {
        "project": {
            "name": "AI-Team",
        },
        "architecture_version": "3.1",
        "dependencies": {
            "legacy": True,
        },
        "tester_feedback": {
            "status": "failed",
        },
        "reviewer_feedback": {
            "status": "revision",
        },
    }

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.metadata == {
        "project": {
            "name": "AI-Team",
        },
        "architecture_version": "3.1",
    }


def test_build_agent_context_preserves_task_without_mutation():
    task = make_task()

    task.result = {
        "message": "done",
    }

    task.test_result = {
        "status": "passed",
    }

    task.review_result = {
        "status": "approved",
    }

    task.status_history = [
        {
            "status": "running",
        }
    ]

    task.context = {
        "project": "AI-Team",
    }

    original_result = deepcopy(task.result)
    original_test_result = deepcopy(task.test_result)
    original_review_result = deepcopy(task.review_result)
    original_status_history = deepcopy(task.status_history)
    original_context = deepcopy(task.context)

    builder = ContextBuilder({})

    builder.build_agent_context(task)

    assert task.result == original_result
    assert task.test_result == original_test_result
    assert task.review_result == original_review_result
    assert task.status_history == original_status_history
    assert task.context == original_context