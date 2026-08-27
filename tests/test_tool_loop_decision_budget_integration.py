from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
from runtime.llm.base import BaseLLM, LLMResponse
from agents.base import BaseAgent


class _RecordingLLM(BaseLLM):
    def __init__(self):
        self.messages_seen = []

    def generate(self, prompt: str, *, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 4096) -> str:
        return "ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        self.messages_seen.append([dict(message) for message in messages])
        return LLMResponse(content="continue")


class _Agent(BaseAgent):
    @property
    def role(self):
        return "developer"

    def run(self, task):
        raise NotImplementedError


def test_decision_budget_injects_checkpoint_without_terminating_loop():
    llm = _RecordingLLM()
    agent = _Agent(AgentConfig(), llm=llm)
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]

    for _ in range(4):
        agent._generate_with_tools(messages)

    assert len(llm.messages_seen) == 4
    assert any("DECISION BUDGET CHECKPOINT" in str(message.get("content")) for message in llm.messages_seen[-1])
    assert agent._tool_loop_decision_budget.decisions == 4


def test_decision_budget_is_task_local_when_message_list_changes():
    llm = _RecordingLLM()
    agent = _Agent(AgentConfig(), llm=llm)
    first_messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task-1"}]
    second_messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task-2"}]

    for _ in range(4):
        agent._generate_with_tools(first_messages)

    agent._generate_with_tools(second_messages)

    assert agent._tool_loop_decision_budget.decisions == 1
    assert not any("DECISION BUDGET CHECKPOINT" in str(message.get("content")) for message in llm.messages_seen[-1])
