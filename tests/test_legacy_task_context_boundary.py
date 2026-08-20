from runtime.context_builder import ContextBuilder
from runtime.task import Task


def make_task(**overrides):
    values = {
        "id": "TASK-001",
        "title": "Demo task",
        "description": "Validate legacy context boundary",
        "role": "developer",
    }
    values.update(overrides)
    return Task(**values)


def test_legacy_task_context_only_supplies_declared_dependency_snapshots():
    task = make_task(
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "Architect result",
                "role": "architect",
                "result": {"schema": "v1"},
            },
            "UNDECLARED": {
                "title": "Must not leak",
                "role": "architect",
                "result": {"secret": True},
            },
        },
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.dependency_context == {
        "TASK-DEP-001": {
            "title": "Architect result",
            "role": "architect",
            "result": {"schema": "v1"},
        }
    }


def test_legacy_dependency_snapshot_is_not_duplicated_as_metadata():
    task = make_task(
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "Architect result",
                "role": "architect",
                "result": {"schema": "v1"},
            },
            "feature_flag": "context-migration",
        },
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.metadata == {"feature_flag": "context-migration"}
    assert "TASK-DEP-001" not in context.metadata


def test_legacy_reserved_context_keys_do_not_replace_canonical_fields():
    task = make_task(
        result={"canonical": True},
        test_result={"status": "passed"},
        review_result={"status": "approved"},
        context={
            "dependencies": {"legacy": True},
            "tester_feedback": {"status": "legacy-failed"},
            "reviewer_feedback": {"status": "legacy-revision"},
            "feature_flag": "canonical-metadata",
        },
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.task_result == {"canonical": True}
    assert context.tester_feedback == {"status": "passed"}
    assert context.reviewer_feedback == {"status": "approved"}
    assert context.metadata == {"feature_flag": "canonical-metadata"}


def test_legacy_context_does_not_populate_execution_result_or_history():
    task = make_task(
        context={
            "result": {"legacy": True},
            "status_history": [{"from": "legacy", "to": "completed"}],
            "test_history": [{"status": "legacy-passed"}],
            "review_history": [{"status": "legacy-approved"}],
        },
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert context.task_result == {}
    assert context.history == []
    assert context.test_history == []
    assert context.review_history == []
    assert context.metadata == {
        "result": {"legacy": True},
        "status_history": [{"from": "legacy", "to": "completed"}],
        "test_history": [{"status": "legacy-passed"}],
        "review_history": [{"status": "legacy-approved"}],
    }


def test_completed_dependency_from_all_tasks_takes_precedence_over_legacy_context():
    dependency = make_task(
        id="TASK-DEP-001",
        title="Canonical dependency",
        role="architect",
        status="completed",
        result={"source": "all_tasks"},
    )
    task = make_task(
        dependencies=["TASK-DEP-001"],
        context={
            "TASK-DEP-001": {
                "title": "Legacy dependency",
                "role": "architect",
                "result": {"source": "legacy"},
            }
        },
    )

    context = ContextBuilder({"TASK-DEP-001": dependency}).build_agent_context(task)

    assert context.dependency_context == {
        "TASK-DEP-001": {
            "title": "Canonical dependency",
            "role": "architect",
            "result": {"source": "all_tasks"},
        }
    }
