from runtime.context_compactor import compact_tool_context


def test_compactor_preserves_system_and_initial_task_messages():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "old"},
        {"role": "tool", "content": "old tool result"},
        {"role": "assistant", "content": "recent"},
        {"role": "tool", "content": "recent tool result"},
    ]

    result = compact_tool_context(messages, recent_messages=2)

    assert result[0] == messages[0]
    assert result[1] == messages[1]
    assert any(
        item.get("role") == "system"
        and "Earlier execution context compacted" in item.get("content", "")
        for item in result
    )
    assert result[-2:] == messages[-2:]


def test_compactor_bounds_large_tool_output():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "old"},
        {"role": "tool", "content": "x" * 100},
        {"role": "assistant", "content": "recent"},
        {"role": "tool", "content": "y" * 100},
    ]

    result = compact_tool_context(messages, recent_messages=2, max_tool_chars=20)

    tool_messages = [item for item in result if item.get("role") == "tool"]
    assert tool_messages
    assert len(tool_messages[-1]["content"]) > 20
    assert "tool output truncated" in tool_messages[-1]["content"]


def test_compactor_does_not_mutate_input_messages():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "x" * 100},
        {"role": "assistant", "content": "recent"},
        {"role": "tool", "content": "y" * 100},
    ]
    original = [dict(message) for message in messages]

    compact_tool_context(messages, recent_messages=2, max_tool_chars=20)

    assert messages == original


def test_compactor_reports_all_older_messages_in_single_marker():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "old-1"},
        {"role": "tool", "content": "old-tool-1"},
        {"role": "assistant", "content": "old-2"},
        {"role": "tool", "content": "old-tool-2"},
        {"role": "assistant", "content": "recent"},
        {"role": "tool", "content": "recent-tool"},
    ]

    result = compact_tool_context(messages, recent_messages=2)
    markers = [
        item for item in result
        if item.get("role") == "system"
        and "Earlier execution context compacted" in item.get("content", "")
    ]

    assert len(markers) == 1
    assert "messages=4" in markers[0]["content"]
    assert "tool_results=2" in markers[0]["content"]
