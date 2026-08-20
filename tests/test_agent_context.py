import pytest

from runtime.agent_context import AgentContext
from runtime.context_builder import ContextBuilder
from runtime.task import Task
from copy import deepcopy

def make_task(**kwargs):
    defaults = {
        "id": "TASK-001",
        "title": "demo",
        "description": "test task",
        "role": "developer",
        "status": "running",
    }

    defaults.update(kwargs)

    return Task(**defaults)


def test_agent_context_accepts_valid_context():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
    )

    assert context.task_id == "TASK-001"
    assert context.task_title == "demo"
    assert context.task_description == "test task"
    assert context.role == "developer"
    assert context.status == "running"
    assert context.review_round == 0
    assert context.dependencies == []
    assert context.task_result == {}
    assert context.tester_feedback == {}
    assert context.reviewer_feedback == {}
    assert context.history == []
    assert context.metadata == {}


def test_agent_context_requires_task_id():
    with pytest.raises(
        ValueError,
        match="task_id",
    ):
        AgentContext(
            task_id="",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
        )


def test_agent_context_requires_task_title():
    with pytest.raises(
        ValueError,
        match="task_title",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="",
            task_description="test task",
            role="developer",
            status="running",
        )


def test_agent_context_requires_task_description_string():
    with pytest.raises(
        ValueError,
        match="task_description",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description=None,
            role="developer",
            status="running",
        )


def test_agent_context_requires_role():
    with pytest.raises(
        ValueError,
        match="role",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="",
            status="running",
        )


def test_agent_context_requires_status():
    with pytest.raises(
        ValueError,
        match="status",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="",
        )


def test_agent_context_requires_non_negative_review_round():
    with pytest.raises(
        ValueError,
        match="review_round",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            review_round=-1,
        )


def test_agent_context_requires_integer_review_round():
    with pytest.raises(
        ValueError,
        match="review_round",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            review_round="1",
        )


def test_agent_context_requires_dependencies_list():
    with pytest.raises(
        ValueError,
        match="dependencies",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            dependencies="TASK-002",
        )


def test_agent_context_requires_dependency_ids_to_be_strings():
    with pytest.raises(
        ValueError,
        match="dependencies",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            dependencies=["TASK-002", 123],
        )


def test_agent_context_requires_dictionary_payloads():
    with pytest.raises(
        ValueError,
        match="task_result",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            task_result=[],
        )


def test_agent_context_requires_tester_feedback_dictionary():
    with pytest.raises(
        ValueError,
        match="tester_feedback",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            tester_feedback=[],
        )


def test_agent_context_requires_reviewer_feedback_dictionary():
    with pytest.raises(
        ValueError,
        match="reviewer_feedback",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            reviewer_feedback=[],
        )


def test_agent_context_requires_history_list():
    with pytest.raises(
        ValueError,
        match="history",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            history={},
        )


def test_agent_context_requires_history_entries_to_be_dicts():
    with pytest.raises(
        ValueError,
        match="history",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            history=[{"event": "start"}, "invalid"],
        )


def test_agent_context_requires_metadata_dictionary():
    with pytest.raises(
        ValueError,
        match="metadata",
    ):
        AgentContext(
            task_id="TASK-001",
            task_title="demo",
            task_description="test task",
            role="developer",
            status="running",
            metadata=[],
        )


def test_agent_context_isolates_nested_task_result():
    result = {
        "implementation": {
            "files": ["runtime/task.py"],
        }
    }

    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        task_result=result,
    )

    result["implementation"]["files"].append(
        "runtime/workflow.py"
    )

    assert context.task_result == {
        "implementation": {
            "files": ["runtime/task.py"],
        }
    }


def test_agent_context_isolates_dependencies():
    dependencies = ["TASK-001", "TASK-002"]

    context = AgentContext(
        task_id="TASK-003",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        dependencies=dependencies,
    )

    dependencies.append("TASK-004")

    assert context.dependencies == [
        "TASK-001",
        "TASK-002",
    ]


def test_agent_context_isolates_history():
    history = [
        {
            "status": "running",
            "metadata": {
                "attempt": 1,
            },
        }
    ]

    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        history=history,
    )

    history[0]["metadata"]["attempt"] = 2

    assert context.history == [
        {
            "status": "running",
            "metadata": {
                "attempt": 1,
            },
        }
    ]


def test_agent_context_isolates_metadata():
    metadata = {
        "source": {
            "name": "architect",
        }
    }

    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        metadata=metadata,
    )

    metadata["source"]["name"] = "reviewer"

    assert context.metadata == {
        "source": {
            "name": "architect",
        }
    }


def test_agent_context_to_dict_returns_snapshot():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        review_round=2,
        dependencies=["TASK-DEP-001"],
        task_result={
            "message": "done",
        },
        tester_feedback={
            "status": "passed",
        },
        reviewer_feedback={
            "status": "approved",
        },
        history=[
            {
                "status": "running",
            }
        ],
        metadata={
            "source": "workflow",
        },
    )

    result = context.to_dict()

    assert result == {
        "task_id": "TASK-001",
        "task_title": "demo",
        "task_description": "test task",
        "role": "developer",
        "status": "running",
        "review_round": 2,
        "dependencies": ["TASK-DEP-001"],
        "task_result": {
            "message": "done",
        },
        "tester_feedback": {
            "status": "passed",
        },
        "reviewer_feedback": {
            "status": "approved",
        },
        "history": [
            {
                "status": "running",
            }
        ],
        "metadata": {
            "source": "workflow",
        },
    }


def test_agent_context_to_dict_is_detached():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        task_result={
            "nested": {
                "value": 1,
            }
        },
    )

    result = context.to_dict()

    result["task_result"]["nested"]["value"] = 2

    assert context.task_result["nested"]["value"] == 1


def test_agent_context_from_dict_accepts_valid_context():
    context = AgentContext.from_dict(
        {
            "task_id": "TASK-001",
            "task_title": "demo",
            "task_description": "test task",
            "role": "developer",
            "status": "running",
            "review_round": 1,
            "dependencies": ["TASK-DEP-001"],
            "task_result": {
                "message": "done",
            },
            "tester_feedback": {
                "status": "passed",
            },
            "reviewer_feedback": {
                "status": "approved",
            },
            "history": [
                {
                    "status": "running",
                }
            ],
            "metadata": {
                "source": "workflow",
            },
        }
    )

    assert context.task_id == "TASK-001"
    assert context.review_round == 1
    assert context.dependencies == ["TASK-DEP-001"]
    assert context.task_result["message"] == "done"
    assert context.tester_feedback["status"] == "passed"
    assert context.reviewer_feedback["status"] == "approved"
    assert context.history[0]["status"] == "running"
    assert context.metadata["source"] == "workflow"


def test_agent_context_from_dict_requires_core_fields():
    with pytest.raises(
        ValueError,
        match="missing required fields",
    ):
        AgentContext.from_dict(
            {
                "task_id": "TASK-001",
            }
        )


def test_agent_context_supports_dict_style_access():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
    )

    assert context["task_id"] == "TASK-001"
    assert context["role"] == "developer"
    assert context["status"] == "running"


def test_agent_context_get_supports_defaults():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
    )

    assert context.get("task_id") == "TASK-001"
    assert context.get("missing") is None
    assert context.get("missing", "default") == "default"


def test_context_builder_builds_agent_context():
    task = make_task()

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert isinstance(context, AgentContext)
    assert context.task_id == "TASK-001"
    assert context.task_title == "demo"
    assert context.task_description == "test task"
    assert context.role == "developer"
    assert context.status == "running"


def test_context_builder_allows_explicit_role():
    task = make_task(
        role="developer",
    )

    builder = ContextBuilder({})

    context = builder.build_agent_context(
        task,
        role="tester",
    )

    assert context.role == "tester"
    assert task.role == "developer"


def test_context_builder_builds_completed_dependencies():
    dependency = make_task(
        id="TASK-DEP-001",
        title="dependency",
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

    context = builder.build_agent_context(task)

    assert context.dependencies == [
        "TASK-DEP-001",
    ]


def test_context_builder_excludes_incomplete_dependencies():
    dependency = make_task(
        id="TASK-DEP-001",
        title="dependency",
        role="architect",
        status="running",
        result={
            "architecture": "not ready",
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

    context = builder.build_agent_context(task)

    assert context.dependencies == []


def test_context_builder_copies_task_result():
    task = make_task(
        result={
            "implementation": {
                "files": ["runtime/task.py"],
            }
        }
    )

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    task.result["implementation"]["files"].append(
        "runtime/workflow.py"
    )

    assert context.task_result == {
        "implementation": {
            "files": ["runtime/task.py"],
        }
    }


def test_context_builder_contains_tester_feedback():
    task = make_task()

    task.test_result = {
        "status": "failed",
        "message": "missing boundary tests",
    }

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.tester_feedback == {
        "status": "failed",
        "message": "missing boundary tests",
    }


def test_context_builder_contains_reviewer_feedback():
    task = make_task(
        status="revision",
    )

    task.review_result = {
        "status": "revision",
        "message": "improve error handling",
    }

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.reviewer_feedback == {
        "status": "revision",
        "message": "improve error handling",
    }


def test_context_builder_contains_review_round():
    task = make_task(
        review_round=3,
    )

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.review_round == 3


def test_context_builder_contains_status_history():
    task = make_task()

    task.status_history = [
        {
            "from": "pending",
            "to": "running",
        },
        {
            "from": "running",
            "to": "review_pending",
        },
    ]

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.history == [
        {
            "from": "pending",
            "to": "running",
        },
        {
            "from": "running",
            "to": "review_pending",
        },
    ]


def test_context_builder_preserves_non_core_context_as_metadata():
    task = make_task()

    task.context = {
        "project_name": "AI-Team",
        "architecture_version": "3.1",
        "dependencies": {
            "legacy": "value",
        },
        "tester_feedback": {
            "status": "failed",
        },
    }

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context.metadata == {
        "project_name": "AI-Team",
        "architecture_version": "3.1",
    }


def test_context_builder_does_not_mutate_task():
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
        "project_name": "AI-Team",
    }

    original_status = task.status
    original_result = deepcopy(task.result)
    original_test_result = deepcopy(task.test_result)
    original_review_result = deepcopy(task.review_result)
    original_history = deepcopy(task.status_history)
    original_context = deepcopy(task.context)

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    assert context is not None

    assert task.status == original_status
    assert task.result == original_result
    assert task.test_result == original_test_result
    assert task.review_result == original_review_result
    assert task.status_history == original_history
    assert task.context == original_context


def test_context_builder_snapshot_isolation_for_task_context():
    task = make_task()

    task.context = {
        "project": {
            "name": "AI-Team",
        }
    }

    builder = ContextBuilder({})

    context = builder.build_agent_context(task)

    task.context["project"]["name"] = "changed"

    assert context.metadata == {
        "project": {
            "name": "AI-Team",
        }
    }


def test_legacy_build_method_still_returns_dictionary():
    task = make_task()

    builder = ContextBuilder({})

    context = builder.build(task)

    assert isinstance(context, dict)
    assert context["dependencies"] == {}
    assert context["tester_feedback"] is None
    assert context["reviewer_feedback"] is None


def test_legacy_build_task_context_api_still_works():
    dependency = make_task(
        id="TASK-DEP-001",
        title="dependency",
        role="architect",
        status="completed",
        result={
            "architecture": "database schema",
        },
    )

    task = make_task(
        dependencies=["TASK-DEP-001"],
    )

    context = ContextBuilder(
        {
            dependency.id: dependency,
            task.id: task,
        }
    ).build(task)

    assert "TASK-DEP-001" in context["dependencies"]

    dependency_context = context["dependencies"]["TASK-DEP-001"]

    assert dependency_context["title"] == "dependency"
    assert dependency_context["role"] == "architect"
    assert (
        dependency_context["result"]["architecture"]
        == "database schema"
    )