from runtime.context_builder import ContextBuilder
from runtime.task import Task


def test_canonical_dependency_snapshot_wins_over_stale_legacy_context():
    dependency = Task(
        id="TASK-DEP-001",
        title="Canonical dependency",
        description="dependency",
        role="architect",
        status="completed",
        result={"source": "canonical"},
    )

    task = Task(
        id="TASK-DEV-001",
        title="Developer task",
        description="developer",
        role="developer",
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "Stale legacy dependency",
                "role": "legacy",
                "result": {"source": "legacy"},
            }
        },
    )

    context = ContextBuilder(
        {dependency.id: dependency}
    ).build_agent_context(task)

    assert context.dependency_context == {
        "TASK-DEP-001": {
            "title": "Canonical dependency",
            "role": "architect",
            "result": {"source": "canonical"},
        }
    }


def test_legacy_context_bridge_accepts_only_dependency_snapshots():
    task = Task(
        id="TASK-DEV-001",
        title="Developer task",
        description="developer",
        role="developer",
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "Legacy dependency",
                "role": "architect",
                "result": {"source": "legacy"},
            },
            "result": {"source": "must-not-be-read"},
            "tester_feedback": {"status": "passed"},
            "reviewer_feedback": {"status": "approved"},
            "history": [{"status": "running"}],
        },
    )

    context = ContextBuilder().build_agent_context(task)

    assert context.dependency_context == {
        "TASK-DEP-001": {
            "title": "Legacy dependency",
            "role": "architect",
            "result": {"source": "legacy"},
        }
    }
    assert context.task_result == {}
    assert context.tester_feedback == {}
    assert context.reviewer_feedback == {}
    assert context.history == []
