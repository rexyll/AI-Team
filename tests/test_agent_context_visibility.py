from copy import deepcopy

import pytest

from runtime.agent_context import AgentContext
from runtime.context_view import CONTEXT_ACCESS_POLICY, context_view


ALL_CONTEXT_FIELDS = {
    "task_id",
    "task_title",
    "task_description",
    "role",
    "status",
    "review_round",
    "dependencies",
    "dependency_context",
    "task_result",
    "tester_feedback",
    "qa_feedback",
    "reviewer_feedback",
    "history",
    "test_history",
    "review_history",
    "metadata",
}


def make_context() -> AgentContext:
    return AgentContext(
        task_id="TASK-VIS-001",
        task_title="Context visibility",
        task_description="Validate role-specific AgentContext visibility.",
        role="developer",
        status="running",
        review_round=3,
        dependencies=["TASK-UPSTREAM-001"],
        dependency_context={
            "TASK-UPSTREAM-001": {
                "result": {"marker": "UPSTREAM_RESULT"},
            }
        },
        task_result={"marker": "TASK_RESULT"},
        tester_feedback={"marker": "TESTER_FEEDBACK"},
        qa_feedback={"marker": "QA_FEEDBACK"},
        reviewer_feedback={"marker": "REVIEWER_FEEDBACK"},
        history=[{"marker": "LIFECYCLE_HISTORY"}],
        test_history=[{"marker": "TEST_HISTORY"}],
        review_history=[{"marker": "REVIEW_HISTORY"}],
        metadata={"marker": "METADATA"},
    )


def test_context_access_policy_covers_every_context_field():
    exposed_fields = set().union(*CONTEXT_ACCESS_POLICY.values())

    assert exposed_fields <= ALL_CONTEXT_FIELDS
    assert exposed_fields == {
        "task_id",
        "task_title",
        "task_description",
        "role",
        "status",
        "review_round",
        "dependencies",
        "dependency_context",
        "task_result",
        "tester_feedback",
        "qa_feedback",
        "reviewer_feedback",
        "history",
        "metadata",
    }


def test_context_view_returns_exact_role_projection():
    context = make_context()

    for role, allowed_fields in CONTEXT_ACCESS_POLICY.items():
        view = context_view(context, role)

        assert set(view) == allowed_fields
        assert set(view) <= ALL_CONTEXT_FIELDS


def test_context_view_does_not_leak_role_forbidden_fields():
    context = make_context()

    for role, allowed_fields in CONTEXT_ACCESS_POLICY.items():
        view = context_view(context, role)
        forbidden_fields = ALL_CONTEXT_FIELDS - allowed_fields

        assert not forbidden_fields.intersection(view)


def test_context_view_returns_detached_values():
    context = make_context()

    original = deepcopy(context)
    developer_view = context_view(context, "developer")

    developer_view["dependencies"].append("TASK-MUTATED")
    developer_view["dependency_context"]["TASK-UPSTREAM-001"]["result"][
        "marker"
    ] = "MUTATED"
    developer_view["task_result"]["marker"] = "MUTATED"
    developer_view["history"][0]["marker"] = "MUTATED"
    developer_view["metadata"]["marker"] = "MUTATED"

    assert context.dependencies == original.dependencies
    assert context.dependency_context == original.dependency_context
    assert context.task_result == original.task_result
    assert context.history == original.history
    assert context.metadata == original.metadata


def test_context_view_is_recomputed_from_context_snapshot():
    context = make_context()

    first_view = context_view(context, "developer")
    first_view["task_result"]["marker"] = "MUTATED"

    second_view = context_view(context, "developer")

    assert second_view["task_result"] == {"marker": "TASK_RESULT"}


def test_context_view_rejects_unknown_role():
    with pytest.raises(ValueError, match="Unsupported AgentContext role"):
        context_view(make_context(), "planner")


def test_context_view_rejects_non_agent_context_input():
    with pytest.raises(TypeError, match="expects AgentContext"):
        context_view({"task_id": "TASK-001"}, "developer")
