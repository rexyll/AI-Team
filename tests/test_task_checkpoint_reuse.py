from runtime.context_builder import ContextBuilder
from runtime.task import Task


def _task_with_result() -> Task:
    return Task(
        id="TASK-CHECKPOINT-001",
        title="Resume from checkpoint",
        description="Continue a developer task from compact prior evidence.",
        role="developer",
        status="running",
        result={
            "status": "failed",
            "agent": "developer",
            "task_id": "TASK-CHECKPOINT-001",
            "data": {
                "files_changed": ["runtime/task.py", "runtime/task.py", "tests/test_task.py"],
                "tests": [{"command": "pytest -q", "result": "passed"}],
                "tool_loop_telemetry": [
                    {"tool_name": "read_file", "category": "exploration"},
                    {"tool_name": "write_file", "category": "execution"},
                    {"tool_name": "run_command", "category": "verification"},
                    {"tool_name": "run_command", "category": "exact_duplicate", "duplicate_of": "CALL-3"},
                ],
                "large_raw_output": "must not be copied into the checkpoint",
            },
        },
    )


def test_developer_context_reuses_compact_task_checkpoint() -> None:
    task = _task_with_result()
    context = ContextBuilder().build_agent_context(task, role="developer")

    checkpoint = context.metadata["task_checkpoint"]
    assert checkpoint["task_id"] == task.id
    assert checkpoint["changed_files"] == ["runtime/task.py", "tests/test_task.py"]
    assert checkpoint["last_command"] == "pytest -q"
    assert checkpoint["tool_call_count"] == 4
    assert checkpoint["duplicate_tool_call_count"] == 1
    assert checkpoint["verification_evidence"]
    assert "large_raw_output" not in checkpoint


def test_task_checkpoint_is_not_exposed_to_other_agent_roles() -> None:
    task = _task_with_result()

    architect_context = ContextBuilder().build_agent_context(task, role="architect")
    reviewer_context = ContextBuilder().build_agent_context(task, role="reviewer")

    assert "task_checkpoint" not in architect_context.metadata
    assert "task_checkpoint" not in reviewer_context.metadata


def test_task_checkpoint_is_detached_from_persisted_result() -> None:
    task = _task_with_result()
    context = ContextBuilder().build_agent_context(task, role="developer")
    checkpoint = context.metadata["task_checkpoint"]

    checkpoint["changed_files"].append("should-not-leak.py")
    checkpoint["tool_categories"]["execution"] = 999

    rebuilt = ContextBuilder().build_agent_context(task, role="developer")
    rebuilt_checkpoint = rebuilt.metadata["task_checkpoint"]

    assert "should-not-leak.py" not in rebuilt_checkpoint["changed_files"]
    assert rebuilt_checkpoint["tool_categories"]["execution"] == 1
