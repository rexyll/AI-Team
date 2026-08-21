from __future__ import annotations

from runtime.agent_context import AgentContext
from runtime.context_builder import ContextBuilder
from runtime.task import Task


def _task(**overrides) -> Task:
    values = {
        "id": "TASK-001",
        "title": "demo",
        "description": "snapshot contract",
        "role": "developer",
        "status": "running",
        "dependencies": [],
    }
    values.update(overrides)
    return Task(**values)


def test_context_snapshot_isolated_from_task_nested_mutations():
    task = _task(
        result={"implementation": {"files": ["app.py"]}},
        context={
            "custom": {"source": {"name": "architect"}},
            "extra": [{"value": 1}],
        },
    )
    task.test_result = {"status": "failed", "details": {"errors": ["E1"]}}
    task.review_result = {"status": "revision", "comments": [{"text": "fix"}]}
    task.status_history = [{"from": "ready", "to": "running", "meta": {"attempt": 1}}]
    task.test_history = [{"status": "failed", "details": {"count": 1}}]
    task.review_history = [{"status": "revision", "comments": [{"text": "fix"}]}]

    dependency = _task(
        id="TASK-DEP-001",
        title="architecture",
        role="architect",
        status="completed",
        result={"architecture": {"database": {"engine": "sqlite"}}},
    )
    task.dependencies = [dependency.id]

    context = ContextBuilder({dependency.id: dependency}).build_agent_context(task)

    task.result["implementation"]["files"].append("tests/test_app.py")
    task.context["custom"]["source"]["name"] = "mutated"
    task.context["extra"][0]["value"] = 2
    task.test_result["details"]["errors"].append("E2")
    task.review_result["comments"].append({"text": "new"})
    task.status_history[0]["meta"]["attempt"] = 2
    task.test_history[0]["details"]["count"] = 2
    task.review_history[0]["comments"][0]["text"] = "mutated"
    dependency.result["architecture"]["database"]["engine"] = "postgres"

    assert context.task_result == {"implementation": {"files": ["app.py"]}}
    assert context.metadata["custom"]["source"]["name"] == "architect"
    assert context.metadata["extra"][0]["value"] == 1
    assert context.tester_feedback == {"status": "failed", "details": {"errors": ["E1"]}}
    assert context.reviewer_feedback == {"status": "revision", "comments": [{"text": "fix"}]}
    assert context.history[0]["meta"]["attempt"] == 1
    assert context.test_history[0]["details"]["count"] == 1
    assert context.review_history[0]["comments"][0]["text"] == "fix"
    assert context.dependency_context[dependency.id]["result"]["architecture"]["database"]["engine"] == "sqlite"


def test_context_snapshot_mutations_do_not_change_source_task():
    task = _task(
        result={"implementation": {"files": ["app.py"]}},
        context={"custom": {"owner": "architect"}},
    )
    task.test_result = {"status": "passed", "details": {"cases": [1]}}
    task.review_result = {"status": "approved", "comments": [{"text": "ok"}]}
    task.status_history = [{"from": "ready", "to": "running"}]

    context = ContextBuilder({}).build_agent_context(task)

    context.task_result["implementation"]["files"].append("tests/test_app.py")
    context.metadata["custom"]["owner"] = "reviewer"
    context.tester_feedback["details"]["cases"].append(2)
    context.reviewer_feedback["comments"][0]["text"] = "changed"
    context.history[0]["from"] = "pending"

    assert task.result == {"implementation": {"files": ["app.py"]}}
    assert task.context == {"custom": {"owner": "architect"}}
    assert task.test_result == {"status": "passed", "details": {"cases": [1]}}
    assert task.review_result == {"status": "approved", "comments": [{"text": "ok"}]}
    assert task.status_history == [{"from": "ready", "to": "running"}]


def test_dependency_snapshot_contains_only_completed_dependencies():
    completed = _task(
        id="TASK-DEP-DONE",
        status="completed",
        result={"nested": {"value": [1]}},
    )
    running = _task(
        id="TASK-DEP-RUNNING",
        status="running",
        result={"nested": {"value": [2]}},
    )
    missing_id = "TASK-DEP-MISSING"
    task = _task(dependencies=[completed.id, running.id, missing_id])

    context = ContextBuilder({completed.id: completed, running.id: running}).build_agent_context(task)

    assert context.dependencies == [completed.id]
    assert set(context.dependency_context) == {completed.id}
    assert running.id not in context.dependency_context
    assert missing_id not in context.dependency_context


def test_dependency_snapshot_is_nested_and_detached_from_source_result():
    dependency = _task(
        id="TASK-DEP-001",
        status="completed",
        result={"artifact": {"files": [{"path": "schema.sql"}]}},
    )
    task = _task(dependencies=[dependency.id])

    context = ContextBuilder({dependency.id: dependency}).build_agent_context(task)

    context.dependency_context[dependency.id]["result"]["artifact"]["files"][0]["path"] = "mutated.sql"

    assert dependency.result == {"artifact": {"files": [{"path": "schema.sql"}]}}


def test_formal_dependency_context_precedes_legacy_task_context():
    dependency = _task(
        id="TASK-DEP-001",
        status="completed",
        result={"canonical": {"value": "from-task-manager"}},
    )
    task = _task(
        dependencies=[dependency.id],
        context={
            "dependencies": {
                dependency.id: {
                    "title": "legacy",
                    "role": "architect",
                    "result": {"canonical": {"value": "legacy"}},
                }
            }
        },
    )

    context = ContextBuilder({dependency.id: dependency}).build_agent_context(task)

    assert context.dependency_context[dependency.id]["result"] == {
        "canonical": {"value": "from-task-manager"}
    }


def test_agent_context_round_trip_preserves_snapshot_data():
    original = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="snapshot contract",
        role="developer",
        status="review_pending",
        review_round=2,
        dependencies=["TASK-DEP-001"],
        dependency_context={"TASK-DEP-001": {"result": {"nested": [1]}}},
        task_result={"implementation": {"files": ["app.py"]}},
        tester_feedback={"status": "passed", "details": {"cases": [1]}},
        reviewer_feedback={"status": "revision", "comments": [{"text": "fix"}]},
        history=[{"status": "running", "meta": {"attempt": 1}}],
        test_history=[{"status": "passed", "details": {"cases": [1]}}],
        review_history=[{"status": "revision", "comments": [{"text": "fix"}]}],
        metadata={"source": {"workflow": "task-workflow"}},
    )

    restored = AgentContext.from_dict(original.to_dict())

    assert restored == original


def test_agent_context_round_trip_is_independent_in_both_directions():
    original = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="snapshot contract",
        role="developer",
        status="running",
        dependency_context={"TASK-DEP-001": {"result": {"values": [1]}}},
        task_result={"nested": {"value": 1}},
        history=[{"meta": {"attempt": 1}}],
    )

    serialized = original.to_dict()
    restored = AgentContext.from_dict(serialized)

    serialized["task_result"]["nested"]["value"] = 2
    restored.task_result["nested"]["value"] = 3
    restored.dependency_context["TASK-DEP-001"]["result"]["values"].append(2)
    restored.history[0]["meta"]["attempt"] = 2

    assert original.task_result["nested"]["value"] == 1
    assert original.dependency_context["TASK-DEP-001"]["result"]["values"] == [1]
    assert original.history[0]["meta"]["attempt"] == 1


def test_build_agent_context_does_not_materialize_snapshot_into_task_context():
    task = _task(context={"existing": {"value": 1}})

    context = ContextBuilder({}).build_agent_context(task)

    assert context.task_id == task.id
    assert task.context == {"existing": {"value": 1}}


def test_agent_context_get_and_item_access_return_detached_nested_payloads():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="snapshot contract",
        role="developer",
        status="running",
        task_result={"nested": {"value": 1}},
        dependency_context={"TASK-DEP-001": {"result": {"value": 1}}},
    )

    item_result = context["task_result"]
    get_result = context.get("dependency_context")
    item_result["nested"]["value"] = 2
    get_result["TASK-DEP-001"]["result"]["value"] = 2

    assert context.task_result["nested"]["value"] == 1
    assert context.dependency_context["TASK-DEP-001"]["result"]["value"] == 1
