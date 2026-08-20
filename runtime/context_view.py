from copy import deepcopy
from typing import Any

from runtime.agent_context import AgentContext


CONTEXT_ACCESS_POLICY: dict[str, frozenset[str]] = {
    "architect": frozenset(
        {
            "task_id",
            "task_title",
            "task_description",
            "role",
            "status",
            "dependencies",
            "dependency_context",
            "task_result",
            "history",
            "metadata",
        }
    ),
    "developer": frozenset(
        {
            "task_id",
            "task_title",
            "task_description",
            "role",
            "status",
            "dependencies",
            "dependency_context",
            "task_result",
            "tester_feedback",
            "reviewer_feedback",
            "history",
            "metadata",
            "review_round",
        }
    ),
    "tester": frozenset(
        {
            "task_id",
            "task_title",
            "task_description",
            "task_result",
        }
    ),
    "reviewer": frozenset(
        {
            "task_id",
            "task_title",
            "task_description",
            "task_result",
            "tester_feedback",
            "reviewer_feedback",
            "dependency_context",
            "history",
            "metadata",
            "review_round",
        }
    ),
}


def context_view(context: AgentContext, role: str) -> dict[str, Any]:
    """Return a detached, role-specific AgentContext projection."""
    if not isinstance(context, AgentContext):
        raise TypeError(
            "context_view() expects AgentContext, "
            f"got {type(context).__name__}"
        )

    try:
        allowed_fields = CONTEXT_ACCESS_POLICY[role]
    except KeyError as exc:
        raise ValueError(f"Unsupported AgentContext role: {role}") from exc

    source = context.to_dict()
    return {
        field: deepcopy(source[field])
        for field in allowed_fields
        if field in source
    }
