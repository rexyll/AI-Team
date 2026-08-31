from __future__ import annotations

from agents.mock_agents import MockAgent
from runtime.task import Task
from runtime.task_manager import TaskManager


def main() -> int:
    task = Task(
        id="EXAMPLE-001",
        title="Deterministic example task",
        description="Demonstrate the production task/agent contract without an external LLM.",
        role="developer",
    )
    manager = TaskManager([task])
    agent = MockAgent("developer")
    result = agent.run(task)
    manager.complete_task(task.id, result)
    final_task = manager.get_task(task.id)
    print(f"task={final_task.id} status={final_task.status} agent={result.agent}")
    return 0 if final_task.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
