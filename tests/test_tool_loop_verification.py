from runtime.tool_loop_verification import (
    record_verification_evidence,
    should_suppress_verification,
)


def test_successful_verification_is_reusable_without_workspace_changes():
    results = [record_verification_evidence(command="pytest -q", result="307 passed", changed_files=[])]

    assert should_suppress_verification(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        command_results=results,
        changed_files=[],
    ) is True


def test_verification_must_rerun_after_a_relevant_file_change():
    results = [
        record_verification_evidence(
            command="pytest -q",
            result="307 passed",
            changed_files=["runtime/task.py"],
        )
    ]

    assert should_suppress_verification(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        command_results=results,
        changed_files=["runtime/task.py", "runtime/task_manager.py"],
    ) is False


def test_failed_verification_is_never_reused():
    results = [record_verification_evidence(command="pytest -q", result="1 failed", changed_files=[])]

    assert should_suppress_verification(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        command_results=results,
        changed_files=[],
    ) is False


def test_non_verification_tools_are_never_suppressed():
    results = [record_verification_evidence(command="pytest -q", result="307 passed", changed_files=[])]

    assert should_suppress_verification(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        command_results=results,
        changed_files=[],
    ) is False


def test_legacy_evidence_without_snapshot_is_only_reused_before_any_change():
    results = [{"command": "pytest -q", "result": "307 passed"}]

    assert should_suppress_verification(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        command_results=results,
        changed_files=[],
    ) is True
    assert should_suppress_verification(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        command_results=results,
        changed_files=["runtime/task.py"],
    ) is False
