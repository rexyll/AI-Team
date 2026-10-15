from runtime.task_checkpoint import build_task_checkpoint_summary


def test_checkpoint_contains_compact_resume_state():
    summary = build_task_checkpoint_summary(
        task_id="TASK-1",
        status="in_progress",
        telemetry=[
            {"tool_name": "read_file", "category": "exploration"},
            {"tool_name": "write_file", "category": "execution"},
            {"tool_name": "run_command", "category": "verification"},
            {"tool_name": "run_command", "category": "exact_duplicate", "duplicate_of": "CALL-3"},
        ],
        changed_files=["runtime/task.py", "runtime/task.py", "tests/test_task.py"],
        command_results=[{"command": "pytest -q", "result": "passed"}],
        dependency_context={"TASK-0": "completed"},
        task_result={"success": True},
    )

    assert summary.task_id == "TASK-1"
    assert summary.status == "in_progress"
    assert summary.changed_files == ("runtime/task.py", "tests/test_task.py")
    assert summary.last_command == "pytest -q"
    assert summary.command_count == 1
    assert summary.tool_call_count == 4
    assert summary.duplicate_tool_call_count == 1
    assert summary.tool_categories == {
        "exact_duplicate": 1,
        "execution": 1,
        "exploration": 1,
        "verification": 1,
    }
    assert len(summary.verification_evidence) == 1


def test_checkpoint_is_detached_from_mutable_inputs():
    dependency = {"TASK-0": {"status": "completed"}}
    result = {"success": True}
    summary = build_task_checkpoint_summary(
        task_id="TASK-2",
        status="completed",
        dependency_context=dependency,
        task_result=result,
    )

    dependency["TASK-0"]["status"] = "failed"
    result["success"] = False
    exported = summary.to_dict()
    assert exported["dependency_context"]["TASK-0"]["status"] == "completed"
    assert exported["task_result"]["success"] is True
