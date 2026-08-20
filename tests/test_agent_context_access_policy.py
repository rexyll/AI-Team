from runtime.agent_context import AgentContext
from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.tester import TesterAgent as RuntimeTesterAgent
from agents.reviewer import ReviewerAgent


MARKERS = {
    "task_id": "CTX_TASK_ID",
    "task_title": "CTX_TASK_TITLE",
    "task_description": "CTX_TASK_DESCRIPTION",
    "role": "CTX_ROLE",
    "status": "CTX_STATUS",
    "review_round": 77,
    "dependencies": ["CTX_DEPENDENCY_ID"],
    "dependency_context": {
        "CTX_DEPENDENCY": {
            "result": "CTX_DEP_RESULT",
        }
    },
    "task_result": {
        "marker": "CTX_TASK_RESULT",
    },
    "tester_feedback": {
        "marker": "CTX_TESTER_FEEDBACK",
    },
    "reviewer_feedback": {
        "marker": "CTX_REVIEWER_FEEDBACK",
    },
    "history": [
        {
            "marker": "CTX_HISTORY",
        }
    ],
    "test_history": [
        {
            "marker": "CTX_TEST_HISTORY",
        }
    ],
    "review_history": [
        {
            "marker": "CTX_REVIEW_HISTORY",
        }
    ],
    "metadata": {
        "marker": "CTX_METADATA",
    },
}


POLICY = {
    "architect": {
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
    },
    "developer": {
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
    },
    "tester": {
        "task_id",
        "task_title",
        "task_description",
        "task_result",
    },
    "reviewer": {
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
    },
}


def make_context() -> AgentContext:
    return AgentContext(**MARKERS)


def _prompt_for(agent):
    context = make_context()

    if isinstance(agent, RuntimeTesterAgent):
        return agent._build_prompt(context)

    if isinstance(agent, ReviewerAgent):
        return agent._build_prompt(context)

    return agent._build_messages(context)[1]["content"]


def _semantic_markers(value):
    """
    Extract semantic markers from nested Context values.

    The Contract Test intentionally does not depend on a particular
    serialization format. A field may be rendered using Python's
    repr(), JSON, a human-readable template, or another presentation
    format. What matters is whether its semantic content reaches the
    Agent prompt.
    """
    if isinstance(value, str):
        return [value]

    if isinstance(value, bool):
        return [str(value)]

    if isinstance(value, (int, float)):
        return [str(value)]

    if isinstance(value, dict):
        markers = []

        for key, item in value.items():
            if isinstance(key, str) and key.startswith("CTX_"):
                markers.append(key)

            markers.extend(_semantic_markers(item))

        return markers

    if isinstance(value, (list, tuple, set)):
        markers = []

        for item in value:
            markers.extend(_semantic_markers(item))

        return markers

    return []

def _assert_field_exposed(prompt: str, field: str) -> None:
    """
    Assert that the semantic contents of an allowed Context field
    are exposed to the Agent prompt.

    The assertion intentionally ignores the serialization format.
    """
    expected_markers = _semantic_markers(MARKERS[field])

    assert expected_markers, (
        f"No semantic markers defined for Context field: {field}"
    )

    for marker in expected_markers:
        assert marker in prompt, (
            f"Expected marker {marker!r} for field {field!r} "
            "was not exposed in the Agent prompt."
        )


def _assert_field_hidden(prompt: str, field: str) -> None:
    """
    Assert that semantic contents of a forbidden Context field
    are not exposed to the Agent prompt.
    """
    forbidden_markers = _semantic_markers(MARKERS[field])

    assert forbidden_markers, (
        f"No semantic markers defined for Context field: {field}"
    )

    for marker in forbidden_markers:
        assert marker not in prompt, (
            f"Forbidden marker {marker!r} for field {field!r} "
            "was exposed in the Agent prompt."
        )


def test_agent_context_access_policy_is_explicit():
    assert set(POLICY) == {
        "architect",
        "developer",
        "tester",
        "reviewer",
    }

    all_fields = set(MARKERS)

    for role, allowed in POLICY.items():
        assert allowed <= all_fields


def test_architect_prompt_exposes_only_architect_context_fields():
    prompt = _prompt_for(ArchitectAgent())

    for field in MARKERS:
        if field in POLICY["architect"]:
            _assert_field_exposed(prompt, field)
        else:
            _assert_field_hidden(prompt, field)


def test_developer_prompt_exposes_only_developer_context_fields():
    prompt = _prompt_for(DeveloperAgent())

    for field in MARKERS:
        if field in POLICY["developer"]:
            _assert_field_exposed(prompt, field)
        else:
            _assert_field_hidden(prompt, field)


def test_tester_prompt_exposes_only_tester_context_fields():
    prompt = _prompt_for(RuntimeTesterAgent())

    for field in MARKERS:
        if field in POLICY["tester"]:
            _assert_field_exposed(prompt, field)
        else:
            _assert_field_hidden(prompt, field)


def test_reviewer_prompt_exposes_only_reviewer_context_fields():
    prompt = _prompt_for(ReviewerAgent())

    for field in MARKERS:
        if field in POLICY["reviewer"]:
            _assert_field_exposed(prompt, field)
        else:
            _assert_field_hidden(prompt, field)