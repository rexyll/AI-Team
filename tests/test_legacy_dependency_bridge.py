from runtime.legacy_dependency_bridge import LegacyDependencyBridge
from runtime.task import Task


def _task(
    task_id: str,
    *,
    status: str = "completed",
    result=None,
    dependencies=None,
    context=None,
):
    task = Task(
        id=task_id,
        title=task_id,
        description=f"{task_id} description",
        role="developer",
        status=status,
        result=result or {},
        dependencies=dependencies or [],
    )
    task.context = context or {}
    return task


def test_canonical_dependency_snapshot_wins_over_legacy_snapshot():
    dependency = _task(
        "TASK-DEP-001",
        result={"source": "canonical"},
    )
    task = _task(
        "TASK-002",
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "legacy title",
                "role": "architect",
                "result": {"source": "legacy"},
            }
        },
    )

    result = LegacyDependencyBridge({dependency.id: dependency}).build(task)

    assert result == {
        "TASK-DEP-001": {
            "title": "TASK-DEP-001",
            "role": "developer",
            "result": {"source": "canonical"},
        }
    }


def test_legacy_dependency_is_fallback_when_canonical_snapshot_is_unavailable():
    task = _task(
        "TASK-002",
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "Architect result",
                "role": "architect",
                "result": {"schema": "sqlite"},
            }
        },
    )

    result = LegacyDependencyBridge({}).build(task)

    assert result["TASK-DEP-001"]["result"] == {"schema": "sqlite"}


def test_legacy_dependency_fallback_requires_declared_snapshot_shape():
    task = _task(
        "TASK-002",
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "result": {"schema": "sqlite"},
            },
            "UNDECLARED": {
                "title": "should not leak",
                "role": "architect",
                "result": {"secret": True},
            },
        },
    )

    result = LegacyDependencyBridge({}).build(task)

    assert result == {}


def test_legacy_dependency_snapshot_is_deep_copied():
    source = {
        "title": "Architect result",
        "role": "architect",
        "result": {"tables": ["accounts"]},
    }
    task = _task(
        "TASK-002",
        dependencies=["TASK-DEP-001"],
        context={"TASK-DEP-001": source},
    )

    result = LegacyDependencyBridge({}).build(task)
    result["TASK-DEP-001"]["result"]["tables"].append("transactions")

    assert source["result"]["tables"] == ["accounts"]
