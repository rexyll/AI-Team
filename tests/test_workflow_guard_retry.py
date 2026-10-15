from __future__ import annotations

from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.provenance import agent_feedback_provenance
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


def _manager(task_id: str = "TASK-GUARD-001") -> TaskManager:
    return TaskManager([Task(
        id=task_id, title="guard retry contract", description="guard trips then the retry completes",
        role="developer", status="ready",
    )])


def _router_with(**agents) -> AgentRouter:
    router = AgentRouter()
    for role, agent in agents.items():
        router.register(role, agent)
    return router


class _GuardTrippingDeveloper:
    """Fails once with a progress-guard trip, then completes."""

    role = "developer"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        if self.calls == 1:
            return AgentResult(
                status="failed",
                agent=self.role,
                task_id=task.id,
                message="tool_loop_progress_guard: repeated exact tool call without progress",
                data={
                    "tool_loop_guard": {"tripped": True, "reason": "repeated exact tool call"},
                    "validation": {"tool_call_count": 4, "files_changed_count": 0},
                },
            )
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message="implementation",
            data={"validation": {"tool_call_count": 3, "files_changed_count": 1}},
        )


class _PassingTester:
    role = "tester"
    calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        provenance = agent_feedback_provenance(
            task_id=task.id, agent_role="tester", evidence_id=f"tester:{task.id}",
            parent_evidence_id=f"developer:{task.id}",
        )
        return AgentResult(
            status="passed", agent=self.role, task_id=task.id,
            message="tester verdict: passed",
            data={"provenance": provenance.to_dict()},
        )


class _PassingReviewer:
    role = "reviewer"
    calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        provenance = agent_feedback_provenance(
            task_id=task.id, agent_role="reviewer", evidence_id=f"reviewer:{task.id}",
            parent_evidence_id=f"tester:{task.id}",
        )
        return AgentResult(
            status="approved", agent=self.role, task_id=task.id,
            message="reviewer verdict: approved",
            data={"provenance": provenance.to_dict()},
        )


def test_guard_trip_gets_one_retry_round_with_feedback(capsys):
    developer = _GuardTrippingDeveloper()
    tester = _PassingTester()
    reviewer = _PassingReviewer()
    workflow = TaskWorkflow(
        task_manager=_manager(),
        developer=developer,
        reviewer=reviewer,
        agent_router=_router_with(developer=developer, tester=tester, reviewer=reviewer),
        tester=tester,
        max_review_rounds=3,
    )
    task = workflow.execute("TASK-GUARD-001")

    assert developer.calls == 2
    assert task.status == "completed"
    feedback = str(task.context.get("reviewer_feedback") or "")
    assert "进度守卫" in feedback
    output = capsys.readouterr().out
    assert "guard retry with feedback" in output


def test_guard_trip_on_final_round_still_fails():
    developer = _GuardTrippingDeveloper()
    tester = _PassingTester()
    reviewer = _PassingReviewer()
    workflow = TaskWorkflow(
        task_manager=_manager(),
        developer=developer,
        reviewer=reviewer,
        agent_router=_router_with(developer=developer, tester=tester, reviewer=reviewer),
        tester=tester,
        max_review_rounds=1,
    )
    task = workflow.execute("TASK-GUARD-001")

    # No rounds remain: the guard trip is terminal, exactly as before.
    assert developer.calls == 1
    assert task.status == "failed"
