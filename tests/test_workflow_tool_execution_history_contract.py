from __future__ import annotations

from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from runtime.workflow import TaskWorkflow


class DeveloperWithHistory:
    def __init__(self) -> None:
        self.tool_execution_history = ToolExecutionHistory()

    def run(self, task):
        self.tool_execution_history.append(
            ToolExecutionRecord(
                execution_id="TOOL-WORKFLOW-001",
                task_id=task.id,
                agent_role="developer",
                tool_name="read_file",
                started_at="2026-08-21T00:00:00+00:00",
                completed_at="2026-08-21T00:00:01+00:00",
                status="completed",
                arguments={"path": "src/app.py"},
                output={"bytes": 42},
                error=None,
            )
        )
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "developer completed",
        }


class Tester:
    def run(self, task):
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "tests passed",
        }


class Reviewer:
    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "approved",
        }


def test_task_workflow_attaches_developer_tool_history_to_task_context():
    task = Task(
        id="TASK-HISTORY-001",
        title="history capture",
        description="capture developer tool history",
        role="developer",
        status="ready",
    )
    manager = TaskManager([task])
    developer = DeveloperWithHistory()
    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=Tester(),
        reviewer=Reviewer(),
        agent_router=object(),
    )

    workflow.execute(task.id)

    history_payload = task.context["tool_execution_history"]
    assert len(history_payload) == 1
    assert history_payload[0]["execution_id"] == "TOOL-WORKFLOW-001"
    assert history_payload[0]["tool_name"] == "read_file"
