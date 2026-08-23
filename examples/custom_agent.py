import sys
from pathlib import Path

# Bootstrap repository-root imports so the file runs standalone
# (``python examples/custom_agent.py``) as well as via pytest.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.agent_config import AgentConfig  # noqa: E402
from runtime.agent_result import AgentResult  # noqa: E402
from agents.base import BaseAgent  # noqa: E402
from runtime.task import Task  # noqa: E402


class ExampleAgent(BaseAgent):
    """Minimal custom Agent using the canonical AgentResult contract."""

    @property
    def role(self) -> str:
        return "example"

    def run(self, task: Task) -> AgentResult:
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message=f"Handled: {task.title}",
            data={"description": task.description},
        )


def build_example_agent() -> ExampleAgent:
    return ExampleAgent(
        AgentConfig(
            role="example",
            model="example-model",
            system_prompt="Return deterministic example results.",
        )
    )


if __name__ == "__main__":
    task = Task(
        id="TASK-EXAMPLE-001",
        title="custom agent example",
        description="Demonstrate the canonical custom-agent contract.",
        role="example",
    )
    print(build_example_agent().run(task).to_dict())
