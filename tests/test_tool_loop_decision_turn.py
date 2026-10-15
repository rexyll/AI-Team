from runtime.tool_loop_decision_turn import classify_decision_turn


def test_terminal_verification_skips_next_llm_turn():
    outcome = classify_decision_turn(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        result="1104 passed",
        status="completed",
        category="verification",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1104 passed"}],
    )
    assert outcome.skip_llm_turn is True
    assert outcome.terminal is True
    assert outcome.decision.reason == "terminal_verification"


def test_duplicate_evidence_skips_redundant_decision_but_is_not_terminal():
    outcome = classify_decision_turn(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="same evidence",
        status="completed",
        category="exact_duplicate",
        duplicate_of="CALL-1",
        changed_files=[],
        command_results=[],
    )
    assert outcome.skip_llm_turn is True
    assert outcome.terminal is False


def test_failure_never_skips_llm_decision():
    outcome = classify_decision_turn(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="Tool error: PermissionError",
        status="failed",
        category="execution",
        changed_files=[],
        command_results=[],
    )
    assert outcome.skip_llm_turn is False
    assert outcome.terminal is False
    assert outcome.decision.reason == "tool_failure_requires_recovery"


def test_reused_verification_never_skips_as_terminal():
    outcome = classify_decision_turn(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        result="Verification evidence reused",
        status="completed",
        category="verification",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1104 passed"}],
        verification_reused=True,
    )
    assert outcome.skip_llm_turn is False
    assert outcome.terminal is False
