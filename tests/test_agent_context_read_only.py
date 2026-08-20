from copy import deepcopy

from runtime.agent_context import AgentContext
from runtime.context_builder import ContextBuilder
from runtime.context_view import context_view
from runtime.task import Task



def make_task() -> Task:
    return Task(
        id="TASK-RO-001",
        title="Read-only execution context",
        description="Validate AgentContext read-only execution conventions.",
        role="developer",
        status="running",
        dependencies=[],
    )



def make_context() -> AgentContext:
    return AgentContext(
        task_id="TASK-RO-001",
        task_title="Read-only execution context",
        task_description="Validate AgentContext read-only execution conventions.",
        role="developer",
        status="running",
        review_round=2,
        dependencies=["TASK-UPSTREAM-001"],
        dependency_context={
            "TASK-UPSTREAM-001": {
                "title": "Architecture",
                "role": "architect",
                "result": {"architecture": {"marker": "ARCH"}},
            }
        },
        task_result={"marker": "TASK_RESULT"},
        tester_feedback={"status": "passed"},
        reviewer_feedback={"status": "revision"},
        history=[{"status": "running"}],
        test_history=[{"status": "passed"}],
        review_history=[{"status": "revision"}],
        metadata={"marker": "METADATA"},
    )



def test_agent_context_is_execution_snapshot_not_task_state():
    task = make_task()
    task.result = {"nested": {"value": 1}}
    task.context = {"project": {"name": "AI-Team"}}

    context = ContextBuilder({}).build_agent_context(task, role="developer")

    context.task_result["nested"]["value"] = 99
    context.metadata["project"]["name"] = "mutated"

    assert task.result == {"nested": {"value": 1}}
    assert task.context == {"project": {"name": "AI-Team"}}



def test_context_view_is_input_only_and_never_a_task_update_path():
    context = make_context()
    original = deepcopy(context)

    view = context_view(context, "developer")
    view["task_result"]["marker"] = "changed"
    view["dependencies"].append("TASK-MUTATED")
    view["history"][0]["status"] = "completed"
    view["metadata"]["marker"] = "changed"

    assert context.task_result == original.task_result
    assert context.dependencies == original.dependencies
    assert context.history == original.history
    assert context.metadata == original.metadata



def test_rebuilding_context_discards_agent_side_projection_mutations():
    task = make_task()
    task.result = {"value": 1}

    first_context = ContextBuilder({}).build_agent_context(task, role="developer")
    first_view = context_view(first_context, "developer")
    first_view["task_result"]["value"] = 999

    second_context = ContextBuilder({}).build_agent_context(task, role="developer")

    assert second_context.task_result == {"value": 1}



def test_context_history_and_current_results_are_runtime_owned_snapshots():
    task = make_task()
    task.test_result = {"status": "passed"}
    task.review_result = {"status": "approved"}
    task.status_history = [{"from": "running", "to": "reviewing"}]
    task.test_history = [{"status": "passed"}]
    task.review_history = [{"status": "approved"}]

    context = ContextBuilder({}).build_agent_context(task, role="reviewer")

    context.tester_feedback["status"] = "failed"
    context.reviewer_feedback["status"] = "revision"
    context.history[0]["to"] = "failed"
    context.test_history[0]["status"] = "failed"
    context.review_history[0]["status"] = "revision"

    assert task.test_result == {"status": "passed"}
    assert task.review_result == {"status": "approved"}
    assert task.status_history == [{"from": "running", "to": "reviewing"}]
    assert task.test_history == [{"status": "passed"}]
    assert task.review_history == [{"status": "approved"}]



def test_agent_context_does_not_provide_mutation_methods_for_task():
    context = make_context()

    assert not hasattr(context, "update_task")
    assert not hasattr(context, "set_status")
    assert not hasattr(context, "record_test_result")
    assert not hasattr(context, "record_review_result")
