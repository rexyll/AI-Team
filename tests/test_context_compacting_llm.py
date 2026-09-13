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


def _messages():
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "old-1"},
        {"role": "tool", "content": "old-tool-1"},
        {"role": "assistant", "content": "old-2"},
        {"role": "tool", "content": "old-tool-2"},
        {"role": "assistant", "content": "recent"},
        {"role": "tool", "content": "recent-tool"},
    ]


def test_context_compacting_llm_sends_bounded_context():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner, recent_messages=2)

    source = _messages()
    llm.generate_with_tools(source)

    sent = inner.messages[0]
    assert len(sent) == 6
    assert sent[0] == source[0]
    assert sent[1] == source[1]
    assert sent[-2:] == source[-2:]
    assert llm.compaction_count == 1
    assert llm.max_input_messages_before == len(source)
    assert llm.max_input_messages_after == len(sent)
    assert llm.max_prompt_chars_before > llm.max_prompt_chars_after


def test_context_compacting_llm_window_never_orphans_tool_messages():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner, recent_messages=8)

    source = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    for index in range(6):
        source.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"call-{index}",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }],
        })
        source.append({"role": "tool", "tool_call_id": f"call-{index}", "content": f"result {index}"})

    llm.generate_with_tools(source)

    sent = inner.messages[0]
    assert sent[0]["role"] == "system"
    assert sent[1]["role"] == "user"
    declared_call_ids = set()
    for message in sent:
        if message["role"] == "assistant":
            declared_call_ids.update(
                call["id"] for call in message.get("tool_calls") or []
            )
        if message["role"] == "tool":
            assert message["tool_call_id"] in declared_call_ids


def test_context_compacting_llm_does_not_mutate_source():
    inner = _FakeLLM()
    llm = ContextCompactingLLM(inner, recent_messages=2, max_tool_chars=10)
    source = _messages()
    original = [dict(message) for message in source]

    llm.generate_with_tools(source)

    assert source == original


def test_context_compacting_llm_delegates_telemetry_attributes():
    class _Instrumented(_FakeLLM):
        stats = object()

    inner = _Instrumented()
    llm = ContextCompactingLLM(inner)

    assert llm.stats is inner.stats
