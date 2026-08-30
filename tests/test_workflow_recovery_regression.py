import pytest

from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.llm.mock import MockLLM
from runtime.persistent_task_manager import PersistentTaskManager
from runtime.task import Task
from runtime.task_state_store import InMemoryTaskStateStore
from runtime.workflow import TaskWorkflow


class _Developer(BaseAgent):
    @property
    def role(self):
        return "developer"

    def run(self, task):
        return AgentResult("completed", self.role, task.id, "done")


class _Reviewer(BaseAgent):
    @property
    def role(self):
        return "reviewer"

    def run(self, task):
        return AgentResult("approved", self.role, task.id, "APPROVED")


def _workflow(manager):
    developer = _Developer(llm=MockLLM("done"))
    reviewer = _Reviewer(llm=MockLLM("APPROVED"))
    router = AgentRouter()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    return TaskWorkflow(manager, developer, reviewer, router)


def test_workflow_can_continue_with_manager_rebuilt_from_persisted_state():
    first = Task("TASK-DONE", "done", "completed", "developer", status="ready")
    second = Task("TASK-NEXT", "next", "resume", "developer", status="ready")
    store = InMemoryTaskStateStore()
    manager = PersistentTaskManager([first, second], state_store=store)
    _workflow(manager).execute(first.id)
    assert store.load(first.id)["status"] == "completed"

    recovered_manager = PersistentTaskManager.from_state_store(store)
    assert recovered_manager.get_task(first.id).status == "completed"
    assert recovered_manager.get_task(first.id).status_history == first.status_history

    result = _workflow(recovered_manager).execute(second.id)
    assert result.status == "completed"
    assert recovered_manager.get_task(first.id).status == "completed"
    assert len(recovered_manager.get_task(first.id).status_history) == len(first.status_history)


def test_recovery_does_not_allow_completed_work_to_be_executed_again():
    task = Task("TASK-DONE", "done", "completed", "developer", status="completed")
    store = InMemoryTaskStateStore()
    store.save(task)
    manager = PersistentTaskManager.from_state_store(store)
    with pytest.raises(ValueError, match="not executable"):
        _workflow(manager).execute(task.id)
