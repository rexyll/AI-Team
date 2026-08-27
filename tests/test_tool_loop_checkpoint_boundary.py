from runtime.tool_loop_checkpoint import collapse_tool_loop_checkpoints


def _checkpoint(calls: int) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"TOOL LOOP CHECKPOINT\ncalls={calls}",
    }


def test_collapse_keeps_only_latest_checkpoint_and_preserves_history() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "action-1"},
        {"role": "tool", "content": "evidence-1"},
        _checkpoint(4),
        {"role": "assistant", "content": "action-2"},
        {"role": "tool", "content": "evidence-2"},
        _checkpoint(8),
        {"role": "assistant", "content": "action-3"},
    ]

    removed = collapse_tool_loop_checkpoints(messages)

    assert removed == 1
    assert [message["content"] for message in messages] == [
        "system",
        "task",
        "action-1",
        "evidence-1",
        "action-2",
        "evidence-2",
        "TOOL LOOP CHECKPOINT\ncalls=8",
        "action-3",
    ]


def test_collapse_is_noop_for_zero_or_one_checkpoint() -> None:
    messages = [{"role": "user", "content": "task"}, _checkpoint(4)]

    assert collapse_tool_loop_checkpoints(messages) == 0
    assert messages[-1] == _checkpoint(4)
