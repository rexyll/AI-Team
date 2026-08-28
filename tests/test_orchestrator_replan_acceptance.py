from __future__ import annotations

import pytest

from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.failure_classification import FailureClass
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow_event_log import WorkflowEventLog


class _Router:
    def get_agent(self, role):
        raise AssertionError("agent execution is not part of this acceptance contract")


def _failed_manager() -> TaskManager:
    task = Task(
        id="TASK-REPLAN-001",
        title="old task",
        description="original requirement",
        role="developer",
        max_retries=0,
    )
    manager = TaskManager([task])
    manager.mark_ready(task.id)
    manager.mark_running(task.id)
    manager.mark_failed(task.id, "specification conflict")
    return manager


def _planner(_: str) -> dict:
    return {
        "project": "demo",
        "summary": "replacement",
        "tasks": [
            {
                "id": "TASK-REPLAN-001",
                "title": "replacement task",
                "description": "replanned requirement",
                "role": "developer",
                "dependencies": [],
            }
        ],
    }


def test_orchestrator_replan_uses_explicit_failure_class_and_live_event_task():
    manager = _failed_manager()
    log = WorkflowEventLog()
    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=_Router(),
        workflow_event_log=log,
        project_id="PROJECT-REPLAN-001",
        replan_planner=_planner,
        recovery_classifier=lambda _: FailureClass.SPECIFICATION,
    )

    assert orchestrator._apply_retry_policy(manager.get_task("TASK-REPLAN-001"), RuntimeError("requirements changed")) is True

    live_task = manager.get_task("TASK-REPLAN-001")
    assert live_task.title == "replacement task"
    assert live_task.status == "pending"
    events = log.list_for_task(live_task.id)
    assert len(events) == 1
    assert events[0].event_type == "task_replanned"
    assert events[0].payload == {
        "status": "pending",
        "attempt": 0,
        "task_count": 1,
    }


def test_orchestrator_replan_failure_preserves_original_graph():
    manager = _failed_manager()

    def failing_planner(_: str) -> dict:
        raise RuntimeError("planner unavailable")

    orchestrator = Orchestrator(
        task_manager=manager,
        agent_router=_Router(),
        replan_planner=failing_planner,
        recovery_classifier=lambda _: FailureClass.SPECIFICATION,
    )

    with pytest.raises(RuntimeError, match="planner unavailable"):
        orchestrator._apply_retry_policy(manager.get_task("TASK-REPLAN-001"), RuntimeError("requirements changed"))

    task = manager.get_task("TASK-REPLAN-001")
    assert task.title == "old task"
    assert task.status == "failed"
    assert task.error == "specification conflict"
