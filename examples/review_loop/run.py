from __future__ import annotations

import sys
from pathlib import Path

# Keep the example directly executable from the repository root without
# requiring installation as a package or PYTHONPATH configuration.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.agent_router import AgentRouter
from runtime.provenance import agent_feedback_provenance
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


class ExampleDeveloper:
    role = "developer"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task: Task) -> dict:
        self.calls += 1
        return {
            "status": "completed",
            "agent": self.role,
            "task_id": task.id,
            "message": f"implementation round {self.calls} completed",
        }


class ExampleTester:
    role = "tester"

    def run(self, task: Task) -> dict:
        return {
            "status": "passed",
            "agent": self.role,
            "task_id": task.id,
            "message": "deterministic tests passed",
            "provenance": agent_feedback_provenance(
                task_id=task.id,
                agent_role=self.role,
                evidence_id=f"tester:{task.id}",
                parent_evidence_id=f"developer:{task.id}",
            ).to_dict(),
        }


class ExampleReviewer:
    role = "reviewer"

    def run(self, task: Task) -> dict:
        return {
            "status": "approved",
            "agent": self.role,
            "task_id": task.id,
            "message": "APPROVED: deterministic review passed",
            "provenance": agent_feedback_provenance(
                task_id=task.id,
                agent_role=self.role,
                evidence_id=f"reviewer:{task.id}",
                parent_evidence_id=f"tester:{task.id}",
            ).to_dict(),
        }


def main() -> int:
    task = Task(
        id="EXAMPLE-REVIEW-001",
        title="Deterministic review-loop example",
        description="Demonstrate Developer -> Tester -> Reviewer using production workflow APIs.",
        role="developer",
        status="ready",
    )
    manager = TaskManager([task])
    developer = ExampleDeveloper()
    tester = ExampleTester()
    reviewer = ExampleReviewer()

    router = AgentRouter()
    router.register("developer", developer)
    router.register("tester", tester)
    router.register("reviewer", reviewer)

    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
    )
    final_task = workflow.execute(task.id)

    print(
        f"task={final_task.id} status={final_task.status} "
        f"developer_calls={developer.calls} review_round={final_task.review_round}"
    )
    return 0 if final_task.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
