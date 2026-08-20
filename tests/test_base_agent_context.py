import pytest

from agents.base import BaseAgent
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.task import Task


class DummyAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def run(self, task: Task) -> AgentResult:
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message="done",
        )


def make_task(**kwargs) -> Task:
    defaults = {
        "id": "TASK-001",
        "title": "demo",
        "description": "test task",
        "role": "developer",
        "status": "running",
    }
    defaults.update(kwargs)
    return Task(**defaults)


def test_base_agent_build_context_returns_agent_context():
    task = make_task()
    agent = DummyAgent()

    context = agent.build_context(task)

    assert isinstance(context, AgentContext)
    assert context.task_id == task.id
    assert context.task_title == task.title
    assert context.task_description == task.description
    assert context.role == agent.role
    assert context.status == task.status


def test_base_agent_build_context_uses_agent_role_override():
    task = make_task(role="architect")
    agent = DummyAgent()

    context = agent.build_context(task)

    assert context.role == "developer"
    assert task.role == "architect"


def test_base_agent_build_context_preserves_completed_dependency_snapshot():
    dependency = make_task(
        id="TASK-000",
        title="dependency",
        role="architect",
        status="completed",
    )
    dependency.result = {
        "architecture": {
            "database": "sqlite",
        },
    }

    task = make_task(dependencies=["TASK-000"])
    agent = DummyAgent()

    context = agent.build_context(
        task,
        all_tasks={dependency.id: dependency, task.id: task},
    )

    assert context.dependencies == ["TASK-000"]

    dependency.result["architecture"]["database"] = "postgresql"

    assert context.task_result == {}
    assert context.dependencies == ["TASK-000"]


def test_base_agent_build_context_does_not_mutate_task():
    task = make_task()
    task.result = {
        "message": "done",
        "nested": {"value": 1},
    }
    task.context = {
        "project_name": "AI-Team",
    }

    agent = DummyAgent()
    original_result = {
        "message": "done",
        "nested": {"value": 1},
    }
    original_context = {
        "project_name": "AI-Team",
    }

    context = agent.build_context(task)

    context.task_result["nested"]["value"] = 2
    context.metadata["project_name"] = "changed"

    assert task.result == original_result
    assert task.context == original_context


def test_base_agent_build_context_rejects_non_task():
    agent = DummyAgent()

    with pytest.raises(TypeError, match="ContextBuilder expects Task"):
        agent.build_context("not-a-task")
