from agents.developer import DeveloperAgent, TOOL_LOOP_CHECKPOINT_INTERVAL


def _telemetry(count: int) -> list[dict]:
    return [
        {
            "execution_id": f"CALL-{index}",
            "tool_name": "read_file",
            "category": "exploration",
            "duplicate_of": None,
            "retry_of": None,
            "result_chars": 10,
            "retained_result_chars": 10,
        }
        for index in range(1, count + 1)
    ]


def test_checkpoint_is_injected_only_at_configured_interval() -> None:
    messages: list[dict] = []
    telemetry = _telemetry(TOOL_LOOP_CHECKPOINT_INTERVAL - 1)

    DeveloperAgent._append_checkpoint(messages, telemetry, [], [])

    assert messages == []


def test_checkpoint_injection_contains_current_loop_state() -> None:
    messages: list[dict] = []
    telemetry = _telemetry(TOOL_LOOP_CHECKPOINT_INTERVAL)

    DeveloperAgent._append_checkpoint(
        messages,
        telemetry,
        ["runtime/task.py"],
        [{"command": "pytest -q", "result": "passed"}],
    )

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "TOOL LOOP CHECKPOINT" in messages[0]["content"]
    assert f"calls={TOOL_LOOP_CHECKPOINT_INTERVAL}" in messages[0]["content"]
    assert "changed_files=runtime/task.py" in messages[0]["content"]
    assert "test_or_command_results=1" in messages[0]["content"]
