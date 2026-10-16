from agents.developer import DeveloperAgent
from runtime.agent_context import AgentContext
from runtime.llm.base import BaseLLM


class _StubLLM(BaseLLM):
    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return ""

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("prompt-building tests must not invoke the model")


def _context(**overrides) -> AgentContext:
    defaults = {
        "task_id": "TASK-001",
        "task_title": "实现模块",
        "task_description": "需求描述",
        "role": "developer",
        "status": "running",
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


def _user_prompt(agent: DeveloperAgent, context: AgentContext) -> str:
    return agent._build_messages(context)[1]["content"]


def agent() -> DeveloperAgent:
    return DeveloperAgent(llm=_StubLLM())


def test_rework_protocol_present_with_reviewer_feedback():
    prompt = _user_prompt(agent(), _context(
        review_round=1,
        reviewer_feedback={"decision": "revision", "summary": "修复导入路径"},
    ))
    assert "返工守则" in prompt
    assert "修复导入路径" in prompt
    assert "这是返工轮" in prompt
    assert "开始工作前先检查工作区" not in prompt


def test_rework_protocol_present_with_tester_feedback():
    prompt = _user_prompt(agent(), _context(
        tester_feedback={"status": "failed", "message": "TEST_FAILED"},
    ))
    assert "返工守则" in prompt
    assert "这是返工轮" in prompt


def test_rework_protocol_present_on_guard_retry_feedback():
    # The guard retry channel reuses the reviewer feedback slot with
    # decision "retry"; the protocol must trigger through it as well.
    prompt = _user_prompt(agent(), _context(
        reviewer_feedback={"decision": "retry", "summary": "上一轮被进度守卫拦截"},
    ))
    assert "返工守则" in prompt


def test_rework_protocol_present_from_review_round_alone():
    prompt = _user_prompt(agent(), _context(review_round=2))
    assert "返工守则" in prompt


def test_first_round_keeps_generic_exploration_instruction():
    prompt = _user_prompt(agent(), _context())
    assert "返工守则" not in prompt
    assert "开始工作前先检查工作区并阅读相关代码。" in prompt
    assert "这是返工轮" not in prompt


def test_protocol_bans_observed_degenerate_patterns():
    prompt = _user_prompt(agent(), _context(review_round=1, reviewer_feedback={"summary": "x"}))
    assert "禁止 python -c" in prompt
    assert "禁止 shell 链式" in prompt
    assert "write_file" in prompt
    assert "python -m pytest" in prompt
    assert "进度守卫" in prompt
    assert "禁止重复发出上一轮已发出且结果未变的调用" in prompt


def test_protocol_requires_direct_first_action():
    prompt = _user_prompt(agent(), _context(review_round=1, reviewer_feedback={"summary": "x"}))
    assert "禁止先做一轮与反馈无关的目录浏览" in prompt
