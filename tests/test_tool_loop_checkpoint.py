from runtime.tool_loop_checkpoint import build_tool_loop_checkpoint


def _telemetry(*categories: str):
    items = []
    for index, category in enumerate(categories, start=1):
        items.append(
            {
                "execution_id": f"CALL-{index}",
                "tool_name": "read_file",
                "category": category,
                "duplicate_of": "CALL-1" if category == "exact_duplicate" else None,
                "retry_of": "CALL-1" if category == "retry" else None,
            }
        )
    return items


def test_checkpoint_is_compact_and_contains_decision_relevant_state():
    checkpoint = build_tool_loop_checkpoint(
        _telemetry("exploration", "execution", "exact_duplicate", "verification"),
        changed_files=["runtime/task.py", "runtime/task.py", "tests/test_task.py"],
        command_results=[{"command": "pytest -q", "result": "passed"}],
    )

    assert checkpoint is not None
    assert "TOOL LOOP CHECKPOINT" in checkpoint
    assert "calls=4 duplicates=1 retries=0" in checkpoint
    assert "categories=exact_duplicate:1, execution:1, exploration:1, verification:1" in checkpoint
    assert "changed_files=runtime/task.py, tests/test_task.py" in checkpoint
    assert "test_or_command_results=1" in checkpoint
    assert "last_command=pytest -q" in checkpoint
    assert "verification_calls=1 execution_calls=1" in checkpoint
    assert "Do not repeat exploration" in checkpoint
    assert "recorded result" in checkpoint


def test_empty_telemetry_does_not_create_noise():
    assert build_tool_loop_checkpoint([]) is None
