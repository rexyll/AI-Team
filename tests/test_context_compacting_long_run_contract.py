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


def _long_tool_history():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    for index in range(10):
        messages.extend(
            [
                {"role": "assistant", "content": f"reasoning-{index}"},
                {"role": "tool", "content": f"tool-result-{index}-" + ("x" * 2000)},
            ]
        )
    return messages


def test_default_window_is_bounded_for_long_tool_loop():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner)

    source = _long_tool_history()
    llm.generate_with_tools(source)

    sent = inner.messages[0]
    assert sent[:2] == source[:2]
    assert len(sent) <= 11
    assert llm.max_input_messages_before == len(source)
    assert llm.max_input_messages_after == len(sent)
    assert llm.max_prompt_chars_after <= llm.context_compactor.config.max_prompt_chars
    assert llm.last_input_tokens_after <= llm.context_compactor.config.max_input_tokens_per_call


def test_older_tool_outputs_are_trimmed_before_hard_budget():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner, recent_messages=8, max_tool_chars=100)

    source = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "reasoning"},
        {"role": "tool", "content": "x" * 1000},
        {"role": "assistant", "content": "latest reasoning"},
        {"role": "tool", "content": "latest tool"},
    ]
    llm.generate_with_tools(source)

    sent = inner.messages[0]
    old_tool = next(message for message in sent if message.get("role") == "tool")
    assert len(old_tool["content"]) < 1000
    assert source[3]["content"] == "x" * 1000
