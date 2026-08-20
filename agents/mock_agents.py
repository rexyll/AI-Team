from agents.base import BaseAgent


class MockAgent(BaseAgent):

    def __init__(self, agent_role: str):
        self._role = agent_role

    @property
    def role(self) -> str:
        return self._role

    def run(self, task):
        return {
            "status": "completed",
            "agent": self.role,
            "task_id": task.id,
            "message": (
                f"{self.role} "
                f"完成任务 {task.id}"
            ),
        }