from runtime.tool_loop_checkpoint import upsert_tool_loop_checkpoint


def _telemetry(count: int) -> list[dict[str, object]]:
    return [
        {
            "execution_id": f"CALL-{index}",
            "tool_name": "read_file",
            "category": "exploration",
            "duplicate_of": None,
            "retry_of": None,
        }
        for index in range(1, count + 1)
    ]


def test_checkpoint_refresh_replaces_previous_summary_instead_of_accumulating() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]

    assert upsert_tool_loop_checkpoint(messages, _telemetry(4)) is True
    assert upsert_tool_loop_checkpoint(messages, _telemetry(8)) is True

    checkpoints = [
        message
        for message in messages
        if message.get("role") == "user"
        and str(message.get("content", "")).startswith("TOOL LOOP CHECKPOINT")
    ]
    assert len(checkpoints) == 1
    assert "calls=8" in str(checkpoints[0]["content"])


def test_checkpoint_upsert_preserves_non_checkpoint_messages() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "action"},
        {"role": "tool", "content": "evidence"},
    ]

    assert upsert_tool_loop_checkpoint(messages, _telemetry(4)) is True
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "user",
    ]


def test_checkpoint_upsert_without_telemetry_is_noop() -> None:
    messages = [{"role": "user", "content": "task"}]

    assert upsert_tool_loop_checkpoint(messages, []) is False
    assert messages == [{"role": "user", "content": "task"}]
