from runtime.agent_context import AgentContext
from runtime.context_builder import ContextBuilder
from runtime.task import Task


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


def test_context_isolated_from_task_nested_mutations():
    dependency = make_task(
        id="TASK-DEP-001",
        title="architecture",
        role="architect",
        status="completed",
        result={
            "architecture": {
                "database": {
                    "engine": "sqlite",
                    "tables": ["accounts"],
                }
            }
        },
    )
    task = make_task(
        dependencies=[dependency.id],
        result={"implementation": {"files": ["app.py"]}},
        context={
            "custom": {"nested": [1]},
        },
        test_result={"status": "failed", "details": {"items": ["x"]}},
        review_result={"status": "revision", "issues": ["issue-1"]},
        status_history=[{"status": "running", "metadata": {"attempt": 1}}],
    )

    context = ContextBuilder({dependency.id: dependency}).build_agent_context(task)

    task.result["implementation"]["files"].append("workflow.py")
    task.context["custom"]["nested"].append(2)
    task.test_result["details"]["items"].append("y")
    task.review_result["issues"].append("issue-2")
    task.status_history[0]["metadata"]["attempt"] = 2
    dependency.result["architecture"]["database"]["tables"].append("transactions")

    assert context.task_result == {"implementation": {"files": ["app.py"]}}
    assert context.metadata["custom"] == {"nested": [1]}
    assert context.tester_feedback["details"]["items"] == ["x"]
    assert context.reviewer_feedback["issues"] == ["issue-1"]
    assert context.history[0]["metadata"]["attempt"] == 1
    assert context.dependency_context[dependency.id]["result"] == {
        "architecture": {
            "database": {
                "engine": "sqlite",
                "tables": ["accounts"],
            }
        }
    }


def test_task_isolated_from_context_nested_mutations():
    dependency = make_task(
        id="TASK-DEP-001",
        title="architecture",
        role="architect",
        status="completed",
        result={"architecture": {"tables": ["accounts"]}},
    )
    task = make_task(
        dependencies=[dependency.id],
        result={"implementation": {"files": ["app.py"]}},
        context={"custom": {"nested": [1]}},
        test_result={"status": "passed", "tests": ["test_app"]},
        review_result={"status": "approved", "issues": []},
        status_history=[{"status": "running"}],
    )

    context = ContextBuilder({dependency.id: dependency}).build_agent_context(task)

    context.task_result["implementation"]["files"].append("workflow.py")
    context.metadata["custom"]["nested"].append(2)
    context.tester_feedback["tests"].append("test_extra")
    context.reviewer_feedback["issues"].append("new")
    context.history[0]["status"] = "completed"
    context.dependency_context[dependency.id]["result"]["architecture"]["tables"].append(
        "transactions"
    )

    assert task.result == {"implementation": {"files": ["app.py"]}}
    assert task.context == {"custom": {"nested": [1]}}
    assert task.test_result == {"status": "passed", "tests": ["test_app"]}
    assert task.review_result == {"status": "approved", "issues": []}
    assert task.status_history == [{"status": "running"}]
    assert dependency.result == {"architecture": {"tables": ["accounts"]}}


def test_dependency_snapshot_only_contains_completed_dependencies():
    completed = make_task(
        id="TASK-DONE",
        status="completed",
        role="architect",
        result={"architecture": "ready"},
    )
    pending = make_task(
        id="TASK-PENDING",
        status="running",
        role="architect",
        result={"architecture": "not ready"},
    )
    task = make_task(
        dependencies=[completed.id, pending.id, "TASK-MISSING"],
    )

    context = ContextBuilder(
        {
            completed.id: completed,
            pending.id: pending,
        }
    ).build_agent_context(task)

    assert context.dependencies == [completed.id]
    assert list(context.dependency_context) == [completed.id]
    assert context.dependency_context[completed.id]["result"] == {
        "architecture": "ready"
    }
    assert pending.id not in context.dependency_context
    assert "TASK-MISSING" not in context.dependency_context


def test_dependency_snapshot_serialization_round_trip_preserves_nested_data():
    context = AgentContext(
        task_id="TASK-002",
        task_title="developer",
        task_description="implement feature",
        role="developer",
        status="running",
        dependencies=["TASK-001"],
        dependency_context={
            "TASK-001": {
                "title": "architecture",
                "role": "architect",
                "result": {
                    "architecture": {
                        "tables": ["accounts"],
                    }
                },
            }
        },
    )

    serialized = context.to_dict()
    restored = AgentContext.from_dict(serialized)

    serialized["dependency_context"]["TASK-001"]["result"]["architecture"][
        "tables"
    ].append("transactions")
    restored.dependency_context["TASK-001"]["result"]["architecture"][
        "tables"
    ].append("audit_log")

    assert context.dependency_context["TASK-001"]["result"]["architecture"][
        "tables"
    ] == ["accounts"]
    assert restored.dependency_context["TASK-001"]["result"]["architecture"][
        "tables"
    ] == ["accounts", "audit_log"]
    assert serialized["dependency_context"]["TASK-001"]["result"]["architecture"][
        "tables"
    ] == ["accounts", "transactions"]


def test_to_dict_and_from_dict_are_detached_from_source_and_restored_context():
    source = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="test task",
        role="developer",
        status="running",
        task_result={"nested": {"values": [1]}},
        tester_feedback={"details": {"items": ["a"]}},
        reviewer_feedback={"issues": ["issue-1"]},
        history=[{"metadata": {"attempt": 1}}],
        metadata={"source": {"name": "workflow"}},
    )

    serialized = source.to_dict()
    restored = AgentContext.from_dict(serialized)

    restored.task_result["nested"]["values"].append(2)
    restored.tester_feedback["details"]["items"].append("b")
    restored.reviewer_feedback["issues"].append("issue-2")
    restored.history[0]["metadata"]["attempt"] = 2
    restored.metadata["source"]["name"] = "agent"

    assert source.task_result == {"nested": {"values": [1]}}
    assert source.tester_feedback == {"details": {"items": ["a"]}}
    assert source.reviewer_feedback == {"issues": ["issue-1"]}
    assert source.history == [{"metadata": {"attempt": 1}}]
    assert source.metadata == {"source": {"name": "workflow"}}


def test_legacy_dependency_snapshot_path_remains_isolated():
    dependency = {
        "TASK-DEP-001": {
            "title": "architecture",
            "role": "architect",
            "result": {"architecture": {"tables": ["accounts"]}},
        }
    }
    task = make_task(
        dependencies=["TASK-DEP-001"],
        context=dependency,
    )

    context = ContextBuilder({}).build_agent_context(task)

    dependency["TASK-DEP-001"]["result"]["architecture"]["tables"].append(
        "transactions"
    )
    context.dependency_context["TASK-DEP-001"]["result"]["architecture"][
        "tables"
    ].append("audit_log")

    assert task.context["TASK-DEP-001"]["result"]["architecture"]["tables"] == [
        "accounts",
        "transactions",
    ]
    assert context.dependency_context["TASK-DEP-001"]["result"]["architecture"][
        "tables"
    ] == ["accounts", "audit_log"]
