from runtime.tool_loop_decision import should_take_terminal_verification_fast_path


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
        command_results=[{"command": "pytest -q", "result": "1100 passed"}, {"command": "pytest tests/test_task.py -q", "result": "12 passed"}],
    ) is False
