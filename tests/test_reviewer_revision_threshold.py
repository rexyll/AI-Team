from agents.reviewer import SYSTEM_PROMPT, ReviewerAgent
from runtime.agent_context import AgentContext


def _context(**overrides) -> AgentContext:
    defaults = {
        "task_id": "TASK-001",
        "task_title": "实现模块",
        "task_description": "需求描述",
        "role": "reviewer",
        "status": "reviewing",
        "review_round": 1,
        "qa_feedback": {"verdict": "concerns", "summary": "疑似边界缺失"},
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


def prompt(**overrides) -> str:
    return ReviewerAgent._build_prompt(_context(**overrides))


def test_system_prompt_contains_revision_threshold():
    assert "修订阈值" in SYSTEM_PROMPT
    assert "疑似" in SYSTEM_PROMPT
    assert "APPROVED 并在原因中列为建议" in SYSTEM_PROMPT
    assert "可执行" in SYSTEM_PROMPT
    assert "默认取向" in SYSTEM_PROMPT


def test_task_prompt_carries_threshold_and_qa_advisory_rules():
    text = prompt()
    assert "修订阈值" in text
    assert "【疑似】级发现不满足修订阈值" in text
    assert "写成建议" in text
    assert "建议性输入" in text


def test_threshold_present_even_without_qa_feedback():
    text = prompt(qa_feedback={})
    assert "修订阈值" in text


def test_parse_review_result_unchanged_by_threshold():
    assert ReviewerAgent._parse_review_result("APPROVED\nok") == "approved"
    assert ReviewerAgent._parse_review_result("REVISION_REQUIRED\nfix x") == "revision"
