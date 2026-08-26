from __future__ import annotations

from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.task import Task


class MockAgent(BaseAgent):
    """Deterministic test double that follows the production Agent contract."""

    def __init__(self, agent_role: str):
        if not isinstance(agent_role, str) or not agent_role.strip():
            raise ValueError("agent_role must be a non-empty string")
        self._role = agent_role.strip()
        super().__init__()

    @property
    def role(self) -> str:
        return self._role

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError(
                "MockAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message=f"{self.role} 完成任务 {task.id}",
        )
