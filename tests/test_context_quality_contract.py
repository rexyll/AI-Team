from runtime.context_builder import ContextBuilder
from runtime.task import Task


def test_developer_context_uses_bounded_checkpoint_instead_of_raw_tool_history():
    task = Task(
        id="TASK-CONTEXT-QUALITY-001",
        title="context quality",
        description="keep raw tool history out of prompt metadata",
        role="developer",
        status="failed",
        context={
            "tool_execution_history": [
                {"execution_id": f"EXEC-{index}", "task_id": "TASK-CONTEXT-QUALITY-001"}
                for index in range(100)
            ],
            "source": "workflow",
        },
        result={
            "data": {
                "files_changed": ["runtime/task.py"],
                "tests": [{"command": "pytest -q", "category": "verification"}],
                "tool_loop_telemetry": [
                    {"tool_name": "read_file", "category": "exploration"}
                ],
            }
        },
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert "tool_execution_history" not in context.metadata
    assert context.metadata["source"] == "workflow"
    assert context.metadata["task_checkpoint"]["task_id"] == task.id
    assert context.metadata["task_checkpoint"]["tool_call_count"] == 1
    assert context.metadata["task_checkpoint"]["changed_files"] == ["runtime/task.py"]
    assert context.metadata["task_checkpoint"]["verification_evidence"]


def test_non_developer_context_never_receives_raw_tool_history():
    task = Task(
        id="TASK-CONTEXT-QUALITY-002",
        title="context quality",
        description="keep telemetry out of role context",
        role="reviewer",
        status="review_pending",
        context={
            "tool_execution_history": [
                {"execution_id": "EXEC-1", "task_id": "TASK-CONTEXT-QUALITY-002"}
            ]
        },
    )

    context = ContextBuilder({}).build_agent_context(task)

    assert "tool_execution_history" not in context.metadata
    assert "task_checkpoint" not in context.metadata
