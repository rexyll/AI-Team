from runtime.tool_loop_classification import classify_tool_call_category


def test_read_tools_are_exploration() -> None:
    assert classify_tool_call_category(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        duplicate_of=None,
        retry_of=None,
    ) == "exploration"


def test_write_file_is_progress_producing() -> None:
    assert classify_tool_call_category(
        tool_name="write_file",
        arguments={"path": "runtime/task.py"},
        duplicate_of=None,
        retry_of=None,
    ) == "progress_producing"


def test_test_command_is_verification() -> None:
    assert classify_tool_call_category(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        duplicate_of=None,
        retry_of=None,
    ) == "verification"


def test_non_test_command_is_execution() -> None:
    assert classify_tool_call_category(
        tool_name="run_command",
        arguments={"command": "python app.py"},
        duplicate_of=None,
        retry_of=None,
    ) == "execution"


def test_duplicate_and_retry_categories_take_precedence() -> None:
    assert classify_tool_call_category(
        tool_name="read_file",
        arguments={"path": "a.py"},
        duplicate_of="EXEC-1",
        retry_of=None,
    ) == "exact_duplicate"
    assert classify_tool_call_category(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        duplicate_of="EXEC-1",
        retry_of="EXEC-1",
    ) == "failure_recovery"
