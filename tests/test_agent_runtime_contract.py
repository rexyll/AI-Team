from __future__ import annotations

import pytest

from agents.base import BaseAgent
from agents.mock_agents import MockAgent
from runtime.agent_result import AgentResult
from runtime.task import Task


def _task() -> Task:
    return Task(
        id="TASK-001",
        title="Runtime contract test",
        description="Verify the common Agent runtime contract.",
        role="developer",
        dependencies=[],
    )


def test_mock_agent_is_a_real_base_agent():
    agent = MockAgent("developer")

    assert isinstance(agent, BaseAgent)
    assert agent.role == "developer"


def test_mock_agent_returns_agent_result():
    result = MockAgent("developer").run(_task())

    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert result.agent == "developer"
    assert result.task_id == "TASK-001"
    assert result.message == "developer 完成任务 TASK-001"
    assert result.data == {}


def test_mock_agent_rejects_invalid_role():
    with pytest.raises(ValueError, match="agent_role must be a non-empty string"):
        MockAgent("")


def test_mock_agent_rejects_invalid_task():
    agent = MockAgent("developer")

    with pytest.raises(TypeError, match="expects Task"):
        agent.run(object())
