from runtime.tool_loop_decision import (
    classify_tool_result_for_decision,
    should_take_terminal_verification_fast_path,
)


def _args(command: str) -> dict[str, str]:
    return {"command": command}


def test_successful_full_suite_verification_can_be_terminal_after_changes():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="1100 passed",
        status="completed",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1100 passed"}],
    ) is True


def test_narrow_verification_is_not_terminal():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("pytest tests/test_task.py -q"),
        result="12 passed",
        status="completed",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest tests/test_task.py -q", "result": "12 passed"}],
    ) is False


def test_failed_verification_is_not_terminal():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="1 failed, 1099 passed",
        status="completed",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1 failed, 1099 passed"}],
    ) is False


def test_verification_without_workspace_changes_is_not_terminal():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="1100 passed",
        status="completed",
        changed_files=[],
        command_results=[{"command": "pytest -q", "result": "1100 passed"}],
    ) is False


def test_non_verification_command_is_not_terminal():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("python -m benchmarks.real_developer --help"),
        result="success",
        status="completed",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "python -m benchmarks.real_developer --help", "result": "success"}],
    ) is False


def test_latest_command_result_must_match_current_command():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="1100 passed",
        status="completed",
        changed_files=["runtime/task.py"],
        command_results=[
            {"command": "pytest -q", "result": "1100 passed"},
            {"command": "pytest tests/test_task.py -q", "result": "12 passed"},
        ],
    ) is False


def test_reused_verification_is_never_terminal():
    assert should_take_terminal_verification_fast_path(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="Verification evidence reused: pytest -q previously succeeded",
        status="completed",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1100 passed"}],
        verification_reused=True,
    ) is False


def test_failed_tool_always_keeps_recovery_decision():
    decision = classify_tool_result_for_decision(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="Tool error: PermissionError",
        status="failed",
        category="execution",
        changed_files=[],
        command_results=[],
    )
    assert decision.requires_llm_decision is True
    assert decision.reason == "tool_failure_requires_recovery"
    assert decision.terminal is False


def test_retry_always_keeps_reassessment_decision():
    decision = classify_tool_result_for_decision(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="1 failed",
        status="completed",
        category="verification",
        retry_of="CALL-1",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1 failed"}],
    )
    assert decision.requires_llm_decision is True
    assert decision.reason == "retry_requires_reassessment"


def test_exact_duplicate_can_reuse_evidence_without_claiming_terminal_success():
    decision = classify_tool_result_for_decision(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="same evidence",
        status="completed",
        category="exact_duplicate",
        duplicate_of="CALL-1",
        changed_files=[],
        command_results=[],
    )
    assert decision.requires_llm_decision is False
    assert decision.reason == "duplicate_evidence_reuse"
    assert decision.terminal is False


def test_successful_full_suite_is_terminal_decision():
    decision = classify_tool_result_for_decision(
        tool_name="run_command",
        arguments=_args("pytest -q"),
        result="1100 passed",
        status="completed",
        category="verification",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1100 passed"}],
    )
    assert decision.requires_llm_decision is False
    assert decision.reason == "terminal_verification"
    assert decision.terminal is True


def test_successful_narrow_verification_requires_followup_decision():
    decision = classify_tool_result_for_decision(
        tool_name="run_command",
        arguments=_args("pytest tests/test_task.py -q"),
        result="12 passed",
        status="completed",
        category="verification",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest tests/test_task.py -q", "result": "12 passed"}],
    )
    assert decision.requires_llm_decision is True
    assert decision.reason == "verification_requires_followup_decision"
    assert decision.terminal is False
