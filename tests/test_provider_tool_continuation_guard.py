from __future__ import annotations

from runtime.llm.base import BaseLLM, LLMResponse
from runtime.llm.provider import ProviderLLM


class _CaptureLLM(ProviderLLM):
    """ProviderLLM that records the wire messages instead of calling a client."""

    def __init__(self):
        super().__init__(model="test-model", client_instance=object())
        self.sent: list[list[dict]] = []

    def _post_chat(self, **kwargs):
        self.sent.append(kwargs["messages"])
        return _FakeResponse()


class _FakeResponse:
    choices = [type("Choice", (), {"message": type("Message", (), {"content": "done", "tool_calls": None})()})()]
    usage = None


def _assistant(tool_call_ids: list[str], content: str = "") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            for call_id in tool_call_ids
        ],
    }


def _tool(call_id: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": "result"}


def test_complete_conversation_is_sent_unchanged():
    llm = _CaptureLLM()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant(["c1"]),
        _tool("c1"),
        _assistant(["c2", "c3"]),
        _tool("c2"),
        _tool("c3"),
    ]

    llm.generate_with_tools(messages)

    assert llm.sent[0] == messages
    assert llm.protocol_repairs == 0


def test_incomplete_tool_turn_is_truncated_before_send():
    llm = _CaptureLLM()
    # The final assistant turn declared c2 but its response was never appended.
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant(["c1"]),
        _tool("c1"),
        _assistant(["c2"]),
    ]

    llm.generate_with_tools(messages)

    assert llm.sent[0] == messages[:4]
    assert llm.protocol_repairs == 1


def test_multi_call_turn_with_partial_responses_keeps_answered_history():
    llm = _CaptureLLM()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant(["c1", "c2"]),
        _tool("c1"),
        _assistant(["c3"]),
        _tool("c3"),
    ]

    llm.generate_with_tools(messages)

    # The turn declaring [c1, c2] keeps its answered declaration c1 and the
    # real tool result; only the unanswered c2 declaration disappears, so the
    # model retains its executed history instead of losing context.
    assert llm.sent[0] == [
        messages[0],
        messages[1],
        {**messages[2], "tool_calls": messages[2]["tool_calls"][:1]},
        messages[3],
        _assistant(["c3"]),
        _tool("c3"),
    ]
    assert llm.protocol_repairs == 1


def test_text_bearing_assistant_survives_declaration_trim():
    llm = _CaptureLLM()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {**_assistant(["c1"]), "content": "Reading the file next."},
    ]

    llm.generate_with_tools(messages)

    assert llm.sent[0] == [
        messages[0],
        messages[1],
        {"role": "assistant", "content": "Reading the file next."},
    ]
    assert llm.protocol_repairs == 1


def test_repair_never_invents_content():
    llm = _CaptureLLM()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant(["c1"]),
        _tool("c1"),
        _assistant(["c2"]),
    ]

    sent = llm.generate_with_tools(messages)
    wire = llm.sent[0]

    assert sent.content == "done"
    for message in wire:
        assert set(message.keys()) <= {"role", "content", "tool_calls", "tool_call_id"}
        if message.get("role") == "tool":
            assert message["tool_call_id"] in {"c1"}
