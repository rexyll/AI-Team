from runtime.agent_context import AgentContext
from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.tester import TesterAgent
from agents.reviewer import ReviewerAgent


MARKERS = {
    "task_id": "CTX_TASK_ID",
    "task_title": "CTX_TASK_TITLE",
    "task_description": "CTX_TASK_DESCRIPTION",
    "role": "CTX_ROLE",
    "status": "CTX_STATUS",
    "review_round": 77,
    "dependencies": ["CTX_DEPENDENCY"],
    "dependency_context": {"CTX_DEPENDENCY": {"result": "CTX_DEP_RESULT"}},
    "task_result": {"marker": "CTX_TASK_RESULT"},
    "tester_feedback": {"marker": "CTX_TESTER_FEEDBACK"},
    "reviewer_feedback": {"marker": "CTX_REVIEWER_FEEDBACK"},
    "history": [{"marker": "CTX_HISTORY"}],
    "test_history": [{"marker": "CTX_TEST_HISTORY"}],
    "review_history": [{"marker": "CTX_REVIEW_HISTORY"}],
    "metadata": {"marker": "CTX_METADATA"},
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
    if isinstance(agent, TesterAgent):
        return agent._build_prompt(context)
    return agent._build_messages(context)[1]["content"]


def test_agent_context_access_policy_is_explicit():
    assert set(POLICY) == {"architect", "developer", "tester", "reviewer"}
    all_fields = set(MARKERS)
    for role, allowed in POLICY.items():
        assert allowed <= all_fields


def test_architect_prompt_exposes_only_architect_context_fields():
    prompt = _prompt_for(ArchitectAgent())
    for field, marker in MARKERS.items():
        marker_text = str(marker)
        if field in POLICY["architect"]:
            assert marker_text in prompt
        else:
            assert marker_text not in prompt


def test_developer_prompt_exposes_only_developer_context_fields():
    prompt = _prompt_for(DeveloperAgent())
    for field, marker in MARKERS.items():
        marker_text = str(marker)
        if field in POLICY["developer"]:
            assert marker_text in prompt
        else:
            assert marker_text not in prompt


def test_tester_prompt_exposes_only_tester_context_fields():
    prompt = _prompt_for(TesterAgent())
    for field, marker in MARKERS.items():
        marker_text = str(marker)
        if field in POLICY["tester"]:
            assert marker_text in prompt
        else:
            assert marker_text not in prompt


def test_reviewer_prompt_exposes_only_reviewer_context_fields():
    prompt = _prompt_for(ReviewerAgent())
    for field, marker in MARKERS.items():
        marker_text = str(marker)
        if field in POLICY["reviewer"]:
            assert marker_text in prompt
        else:
            assert marker_text not in prompt
