from unittest.mock import patch

from agents.developer import DeveloperAgent
from runtime.llm.base import LLMResponse, LLMToolCall
from runtime.task import Task


def test_developer_tool_message_reduces_large_command_output() -> None:
    source = "setup output\n" + ("noise\n" * 2000) + "FAILED tests/test_example.py::test_case - assertion details"

    message = DeveloperAgent._build_tool_message("run_command", source)

    assert len(message) < len(source)
    assert message.endswith("FAILED tests/test_example.py::test_case - assertion details")
    assert "tool evidence truncated" in message


def test_developer_tool_message_keeps_large_file_head_and_tail() -> None:
    source = "from package import dependency\n" + ("body\n" * 2000) + "# important footer"

    message = DeveloperAgent._build_tool_message("read_file", source)

    assert len(message) < len(source)
    assert message.startswith("from package import dependency")
    assert message.endswith("# important footer")
    assert "tool evidence truncated" in message


def test_developer_tool_message_preserves_small_results() -> None:
    source = "3 passed in 0.42s"

    assert DeveloperAgent._build_tool_message("run_command", source) == source


def test_developer_cache_hit_injects_compact_cached_evidence() -> None:
    source = "from package import dependency\n" + ("body\n" * 2000) + "# important footer"
    tool_call_1 = LLMToolCall(call_id="call-1", name="read_file", arguments='{"path":"src/example.py"}')
    tool_call_2 = LLMToolCall(call_id="call-2", name="read_file", arguments='{"path":"src/example.py"}')
    responses = iter(
        [
            LLMResponse(tool_calls=(tool_call_1,)),
            LLMResponse(tool_calls=(tool_call_2,)),
            LLMResponse(content="done"),
        ]
    )
    seen_messages: list[list[dict]] = []
    tool_invocations: list[dict] = []

    def fake_generate(self, messages, *, tools=None, tool_choice="auto"):
        seen_messages.append([dict(message) for message in messages])
        return next(responses)

    def fake_tool(**arguments):
        tool_invocations.append(arguments)
        return source

    task = Task(
        id="TASK-CACHE-EVIDENCE",
        title="cache evidence",
        description="verify cached read-only evidence stays compact",
        role="developer",
        status="running",
    )

    with patch.object(DeveloperAgent, "_generate_with_tools", fake_generate), patch.object(
        DeveloperAgent, "_build_messages", return_value=[]
    ), patch("agents.developer.TOOL_REGISTRY.get", return_value=fake_tool), patch(
        "agents.developer.TOOL_REGISTRY.schema", return_value={}
    ), patch("agents.developer.TOOL_REGISTRY.schemas", return_value=[]):
        result = DeveloperAgent().run(task)

    assert result.status == "completed"
    assert tool_invocations == [{"path": "src/example.py"}]
    assert len(seen_messages) == 3

    second_turn_tool_messages = [
        message for message in seen_messages[2] if message.get("role") == "tool"
    ]
    assert second_turn_tool_messages
    cached_message = second_turn_tool_messages[-1]["content"]
    assert "TOOL RESULT REUSED" in cached_message
    assert "Source execution=call-1" in cached_message
    assert source not in cached_message

    assert result.data["tool_loop_cache"]["hits"] == 1
    assert result.data["tool_loop_cache"]["misses"] == 1
