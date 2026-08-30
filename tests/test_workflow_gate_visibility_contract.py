"""Gate progression observability and terminal-state contracts."""

from __future__ import annotations

from pathlib import Path

from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.provenance import agent_feedback_provenance
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


def _manager(task_id: str = "TASK-GATE-001") -> TaskManager:
    return TaskManager([Task(
        id=task_id, title="gate contract", description="gate visibility and terminal state",
        role="developer", status="ready",
    )])


def _router_with(**agents) -> AgentRouter:
    router = AgentRouter()
    for role, agent in agents.items():
        router.register(role, agent)
    return router


def _feedback(task: Task, role: str, *, evidence_id: str | None = None,
              parent_evidence_id: str | None = None) -> dict:
    if parent_evidence_id is None:
        parent_evidence_id = f"tester:{task.id}" if role == "reviewer" else f"developer:{task.id}"
    return agent_feedback_provenance(
        task_id=task.id,
        agent_role=role,
        evidence_id=evidence_id or f"{role}:{task.id}",
        parent_evidence_id=parent_evidence_id,
    ).to_dict()


class _StubDeveloper:
    role = "developer"

    def run(self, task: Task) -> AgentResult:
        return AgentResult(status="completed", agent=self.role, task_id=task.id, message="implementation")


class _StubTester:
    role = "tester"

    def __init__(self, status: str) -> None:
        self._status = status
        self.calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        return AgentResult(
            status=self._status, agent=self.role, task_id=task.id,
            message=f"tester verdict: {self._status}",
            data={"provenance": _feedback(task, "tester")},
        )


class _StubReviewer:
    role = "reviewer"

    def __init__(self, status: str) -> None:
        self._status = status
        self.calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        return AgentResult(
            status=self._status, agent=self.role, task_id=task.id,
            message=f"reviewer verdict: {self._status}",
            data={"provenance": _feedback(task, "reviewer")},
        )


def _workflow(task_id: str, developer, tester, reviewer, *, max_review_rounds=3):
    return TaskWorkflow(
        task_manager=_manager(task_id), developer=developer, reviewer=reviewer,
        agent_router=_router_with(developer=developer, tester=tester, reviewer=reviewer),
        tester=tester, max_review_rounds=max_review_rounds,
    )


def test_gate_decisions_are_visible_on_console(capsys) -> None:
    developer, tester, reviewer = _StubDeveloper(), _StubTester("passed"), _StubReviewer("approved")
    _workflow("TASK-GATE-001", developer, tester, reviewer).execute("TASK-GATE-001")
    output = capsys.readouterr().out
    assert "[Gate] TASK-GATE-001 round 1/3: developer=completed" in output
    assert "[Gate] TASK-GATE-001 round 1/3: tester=passed" in output
    assert "[Gate] TASK-GATE-001 round 1/3: reviewer=approved" in output


def test_developer_line_reports_objective_metrics(capsys) -> None:
    class _NoToolDeveloper:
        role = "developer"
        def run(self, task: Task) -> AgentResult:
            return AgentResult(
                status="completed", agent=self.role, task_id=task.id, message="text-only report",
                data={"validation": {"tool_call_count": 0, "files_changed_count": 0}},
            )
    developer, tester, reviewer = _NoToolDeveloper(), _StubTester("passed"), _StubReviewer("approved")
    _workflow("TASK-GATE-001", developer, tester, reviewer).execute("TASK-GATE-001")
    assert "developer=completed, tool_calls=0, files_changed=0" in capsys.readouterr().out


def test_tester_rejection_prints_verdict_note(capsys) -> None:
    verdict_text = "TEST_FAILED - no implementation artifacts were produced"
    class _MessageTester:
        role = "tester"
        def run(self, task: Task) -> AgentResult:
            return AgentResult(
                status="failed", agent=self.role, task_id=task.id, message=verdict_text,
                data={"provenance": _feedback(task, "tester")},
            )
    developer, reviewer, tester = _StubDeveloper(), _StubReviewer("approved"), _MessageTester()
    _workflow("TASK-GATE-002", developer, tester, reviewer, max_review_rounds=1).execute("TASK-GATE-002")
    output = capsys.readouterr().out
    assert "tester note:" in output
    assert "no implementation artifacts" in output


def test_reviewer_invalid_verdicts_tolerated_then_recover(capsys) -> None:
    class _SequencedReviewer(_StubReviewer):
        def __init__(self, statuses):
            super().__init__("approved")
            self._statuses = list(statuses)
        def run(self, task: Task) -> AgentResult:
            self.calls += 1
            status = self._statuses.pop(0) if self._statuses else "approved"
            return AgentResult(
                status=status, agent=self.role, task_id=task.id, message=f"verdict {status}",
                data={"provenance": _feedback(
                    task, "reviewer", evidence_id=f"reviewer:{task.id}:attempt:{self.calls}"
                )},
            )
    developer, tester = _StubDeveloper(), _StubTester("passed")
    reviewer = _SequencedReviewer(["weird", "weird", "approved"])
    result = _workflow("TASK-GATE-003", developer, tester, reviewer).execute("TASK-GATE-003")
    assert result.status == "completed"
    assert reviewer.calls >= 3
    assert capsys.readouterr().out.count("retrying with fresh completion") >= 2


def test_tester_persistent_inconclusive_fails_without_limbo(capsys) -> None:
    developer, tester, reviewer = _StubDeveloper(), _StubTester("inconclusive"), _StubReviewer("approved")
    result = _workflow("TASK-GATE-004", developer, tester, reviewer, max_review_rounds=2).execute("TASK-GATE-004")
    assert result.status == "failed"
    assert "inconclusive" in (result.error or "")


def test_developer_zero_artifact_completion_fails_loudly() -> None:
    from agents.developer import DeveloperAgent
    from runtime.llm.mock import MockLLM
    agent = DeveloperAgent(llm=MockLLM("我已完成实现，一切正常。"))
    task = Task(id="T-ZERO", title="zero-artifact regression", description="implement the module", role="developer")
    result = agent.run(task)
    assert result.status == "failed"
    assert "no artifacts" in result.message
    assert result.data["validation"]["tool_call_count"] == 0


def test_developer_prompt_pins_rework_hard_rules() -> None:
    source = (Path(__file__).resolve().parents[1] / "agents" / "developer.py").read_text(encoding="utf-8-sig")
    for token in ("收到返工要求或测试未通过时", "未实际创建文件、未调用工具", "禁止再次仅输出文字说明", "每一轮都必须有可验证的新增动作"):
        assert token in source, f"developer prompt must pin rework rule: {token}"


def test_tester_rejection_rounds_terminate_explicitly(capsys) -> None:
    developer, tester, reviewer = _StubDeveloper(), _StubTester("failed"), _StubReviewer("approved")
    result = _workflow("TASK-GATE-001", developer, tester, reviewer, max_review_rounds=2).execute("TASK-GATE-001")
    assert result.status == "failed"
    assert result.error is not None
    assert "质量门禁" in result.error
    assert "tester" in result.error
    assert reviewer.calls == 0
    output = capsys.readouterr().out
    assert "[Gate] TASK-GATE-001 round 1/2: tester=failed" in output
    assert "[Gate] TASK-GATE-001 round 2/2: tester=failed" in output
    assert "质量门禁在 2 轮内未通过" in output


def test_reviewer_revision_exhaustion_also_terminates(capsys) -> None:
    developer, tester, reviewer = _StubDeveloper(), _StubTester("passed"), _StubReviewer("revision")
    result = _workflow("TASK-GATE-001", developer, tester, reviewer, max_review_rounds=2).execute("TASK-GATE-001")
    assert result.status == "failed"
    output = capsys.readouterr().out
    assert "[Gate] TASK-GATE-001 round 1/2: reviewer=revision" in output
    assert "质量门禁" in (result.error or "") or "failed review" in (result.error or "").lower()
