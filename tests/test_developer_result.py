from agents.developer import DeveloperAgent


def test_build_result_data_contains_structured_fields():
    result = DeveloperAgent._build_result_data(
        content="Implemented task successfully.",
        changed_files=[
            "runtime/task.py",
            "runtime/task_manager.py",
        ],
        command_results=[
            {
                "command": "pytest -q",
                "result": "307 passed",
            }
        ],
        tool_calls=[
            {
                "name": "write_file",
                "arguments": {
                    "path": "runtime/task.py",
                },
            },
            {
                "name": "run_command",
                "arguments": {
                    "command": "pytest -q",
                },
            },
        ],
    )

    assert result["summary"] == (
        "Implemented task successfully."
    )

    assert result["files_changed"] == [
        "runtime/task.py",
        "runtime/task_manager.py",
    ]

    assert result["tests"] == [
        {
            "command": "pytest -q",
            "result": "307 passed",
        }
    ]

    assert result["validation"] == {
        "tool_call_count": 2,
        "test_command_count": 1,
        "files_changed_count": 2,
    }

    assert result["report"] == (
        "Implemented task successfully."
    )


def test_record_write_file_evidence():
    changed_files = []
    command_results = []

    DeveloperAgent._record_tool_evidence(
        tool_name="write_file",
        arguments={
            "path": "runtime/task.py",
        },
        result="ok",
        changed_files=changed_files,
        command_results=command_results,
    )

    assert changed_files == [
        "runtime/task.py",
    ]

    assert command_results == []


def test_record_write_file_does_not_duplicate_file():
    changed_files = [
        "runtime/task.py",
    ]

    command_results = []

    DeveloperAgent._record_tool_evidence(
        tool_name="write_file",
        arguments={
            "path": "runtime/task.py",
        },
        result="ok",
        changed_files=changed_files,
        command_results=command_results,
    )

    assert changed_files == [
        "runtime/task.py",
    ]


def test_record_run_command_evidence():
    changed_files = []
    command_results = []

    DeveloperAgent._record_tool_evidence(
        tool_name="run_command",
        arguments={
            "command": "pytest -q",
        },
        result="307 passed",
        changed_files=changed_files,
        command_results=command_results,
    )

    assert changed_files == []

    assert command_results == [
        {
            "command": "pytest -q",
            "result": "307 passed",
        }
    ]


def test_record_other_tool_does_not_create_execution_evidence():
    changed_files = []
    command_results = []

    DeveloperAgent._record_tool_evidence(
        tool_name="read_file",
        arguments={
            "path": "runtime/task.py",
        },
        result="file content",
        changed_files=changed_files,
        command_results=command_results,
    )

    assert changed_files == []
    assert command_results == []