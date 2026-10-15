from runtime.llm.base import BaseLLM, LLMResponse
from runtime.llm.context_compacting import ContextCompactingLLM


class _FakeLLM(BaseLLM):
    def __init__(self):
        self.messages = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return "ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        self.messages.append([dict(message) for message in messages])
        return LLMResponse(content="ok")


def test_current_tool_result_is_bounded_before_global_context_compaction():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner, recent_messages=8, max_tool_chars=100)
    source = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "inspect"},
        {"role": "tool", "content": "A" * 250 + "TEST SUMMARY: passed"},
    ]

    llm.generate_with_tools(source)

    sent_tool = inner.messages[0][-1]["content"]
    assert len(sent_tool) == 100
    assert sent_tool.startswith("A")
    assert sent_tool.endswith("TEST SUMMARY: passed")
    assert "tool output capped" in sent_tool


def test_tool_result_evidence_reduction_does_not_mutate_source():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner, max_tool_chars=50)
    source = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "X" * 200},
    ]
    original = [dict(message) for message in source]

    llm.generate_with_tools(source)

    assert source == original
