"""Gate progression observability and terminal-state contracts.

Run6 of the real-provider validation exposed two gaps: the quality-gate
loop printed nothing about stage verdicts (a failing tester was invisible),
and exhausting the round budget through the tester-continue path left the
task in a non-terminal "running" limbo that stalled the project scheduler.
These contracts pin the fix: every gate decision is visible, and round
exhaustion terminates the task explicitly with a reason.
"""

from __future__ import annotations

from pathlib import Path

from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


def _manager(task_id: str = "TASK-GATE-001") -> TaskManager:
    task = Task(
        id=task_id,
        title="gate contract",
        description="gate visibility and terminal state",
        role="developer",
        status="ready",
    )
    return TaskManager([task])


def _router_with(**agents) -> AgentRouter:
    router = AgentRouter()
    for role, agent in agents.items():
        router.register(role, agent)
    return router


class _StubDeveloper:
    role = "developer"

    def run(self, task: Task) -> AgentResult:
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message="implementation",
        )


class _StubTester:
    role = "tester"

    def __init__(self, status: str) -> None:
        self._status = status
        self.calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        return AgentResult(
            status=self._status,
            agent=self.role,
            task_id=task.id,
            message=f"tester verdict: {self._status}",
        )


class _StubReviewer:
    role = "reviewer"

    def __init__(self, status: str) -> None:
        self._status = status
        self.calls = 0

    def run(self, task: Task) -> AgentResult:
        self.calls += 1
        return AgentResult(
            status=self._status,
            agent=self.role,
            task_id=task.id,
            message=f"reviewer verdict: {self._status}",
        )


def test_gate_decisions_are_visible_on_console(capsys) -> None:
    developer = _StubDeveloper()
    tester = _StubTester("passed")
    reviewer = _StubReviewer("approved")
    router = _router_with(developer=developer, tester=tester, reviewer=reviewer)

    workflow = TaskWorkflow(
        task_manager=_manager(),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
    )

    workflow.execute("TASK-GATE-001")

    output = capsys.readouterr().out
    assert "[Gate] TASK-GATE-001 round 1/3: developer=completed" in output
    assert "[Gate] TASK-GATE-001 round 1/3: tester=passed" in output
    assert "[Gate] TASK-GATE-001 round 1/3: reviewer=approved" in output


def test_developer_line_reports_objective_metrics(capsys) -> None:
    """run9/run10 regression: a developer that returns completed with ZERO
    tool calls must be visible as such on the gate line."""

    class _NoToolDeveloper:
        role = "developer"

        def run(self, task: Task) -> AgentResult:
            return AgentResult(
                status="completed",
                agent=self.role,
                task_id=task.id,
                message="text-only report",
                data={"validation": {"tool_call_count": 0, "files_changed_count": 0}},
            )

    developer = _NoToolDeveloper()
    tester = _StubTester("passed")
    reviewer = _StubReviewer("approved")
    router = _router_with(developer=developer, tester=tester, reviewer=reviewer)

    workflow = TaskWorkflow(
        task_manager=_manager(),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
    )

    workflow.execute("TASK-GATE-001")

    output = capsys.readouterr().out
    assert "developer=completed, tool_calls=0, files_changed=0" in output


def test_tester_rejection_prints_verdict_note(capsys) -> None:
    verdict_text = "TEST_FAILED - no implementation artifacts were produced"

    class _MessageTester:
        role = "tester"

        def run(self, task: Task) -> AgentResult:
            return AgentResult(
                status="failed",
                agent=self.role,
                task_id=task.id,
                message=verdict_text,
            )

    developer = _StubDeveloper()
    reviewer = _StubReviewer("approved")
    message_tester = _MessageTester()
    router = _router_with(
        developer=developer, tester=message_tester, reviewer=reviewer
    )

    workflow = TaskWorkflow(
        task_manager=_manager("TASK-GATE-002"),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=message_tester,
        max_review_rounds=1,
    )

    workflow.execute("TASK-GATE-002")

    output = capsys.readouterr().out
    assert "tester note:" in output
    assert "no implementation artifacts" in output


def test_reviewer_invalid_verdicts_tolerated_then_recover(capsys) -> None:
    """Transient empty/garbage reviewer responses are retried inline (no
    state change) and the gate recovers once a parseable verdict arrives."""

    class _SequencedReviewer(_StubReviewer):
        def __init__(self, statuses):
            super().__init__("approved")
            self._statuses = list(statuses)

        def run(self, task: Task) -> AgentResult:
            self.calls += 1
            status = (
                self._statuses.pop(0)
                if self._statuses
                else "approved"
            )
            result = super().run(task)
            if self._statuses or True:
                pass
            return AgentResult(
                status=status,
                agent=self.role,
                task_id=task.id,
                message=f"verdict {status}",
            )

    developer = _StubDeveloper()
    tester = _StubTester("passed")
    reviewer = _SequencedReviewer(["weird", "weird", "approved"])
    router = _router_with(developer=developer, tester=tester, reviewer=reviewer)

    workflow = TaskWorkflow(
        task_manager=_manager("TASK-GATE-003"),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
    )

    result = workflow.execute("TASK-GATE-003")

    assert result.status == "completed"
    # 不变量：前两轮各容忍一次无效判定后，第三次给出可解析通过判定。
    assert reviewer.calls >= 3
    output = capsys.readouterr().out
    assert output.count("retrying with fresh completion") >= 2


def test_tester_persistent_inconclusive_fails_without_limbo(capsys) -> None:
    developer = _StubDeveloper()
    tester = _StubTester("inconclusive")
    reviewer = _StubReviewer("approved")
    router = _router_with(developer=developer, tester=tester, reviewer=reviewer)

    workflow = TaskWorkflow(
        task_manager=_manager("TASK-GATE-004"),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
        max_review_rounds=2,
    )

    result = workflow.execute("TASK-GATE-004")

    # 无悬挂：终态明确为失败，错误信息可诊断。
    assert result.status == "failed"
    assert "inconclusive" in (result.error or "")


def test_developer_zero_artifact_completion_fails_loudly() -> None:
    """run9-11 regression: a text-only turn with ZERO tool invocations must
    fail loudly instead of masquerading as a successful implementation."""

    from agents.developer import DeveloperAgent
    from runtime.llm.mock import MockLLM

    agent = DeveloperAgent(llm=MockLLM("我已完成实现，一切正常。"))
    task = Task(
        id="T-ZERO",
        title="zero-artifact regression",
        description="implement the module",
        role="developer",
    )

    result = agent.run(task)

    assert result.status == "failed"
    assert "no artifacts" in result.message
    assert result.data["validation"]["tool_call_count"] == 0


def test_developer_prompt_pins_rework_hard_rules() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "agents" / "developer.py"
    ).read_text(encoding="utf-8-sig")

    for token in (
        "收到返工要求或测试未通过时",
        "未实际创建文件、未调用工具",
        "禁止再次仅输出文字说明",
        "每一轮都必须有可验证的新增动作",
    ):
        assert token in source, f"developer prompt must pin rework rule: {token}"


def test_tester_rejection_rounds_terminate_explicitly(capsys) -> None:
    """run6 regression: repeated tester rejections used to leave the task in
    a non-terminal running state after the round budget silently ran out."""
    developer = _StubDeveloper()
    tester = _StubTester("failed")
    reviewer = _StubReviewer("approved")
    reviewer_calls = reviewer.calls
    router = _router_with(developer=developer, tester=tester, reviewer=reviewer)

    workflow = TaskWorkflow(
        task_manager=_manager(),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
        max_review_rounds=2,
    )

    result = workflow.execute("TASK-GATE-001")

    assert result.status == "failed"
    assert result.error is not None
    assert "质量门禁" in result.error
    assert "tester" in result.error
    # Reviewer must never be reached while the tester keeps rejecting.
    assert reviewer.calls == reviewer_calls

    output = capsys.readouterr().out
    assert "[Gate] TASK-GATE-001 round 1/2: tester=failed" in output
    assert "[Gate] TASK-GATE-001 round 2/2: tester=failed" in output
    assert "质量门禁在 2 轮内未通过" in output


def test_reviewer_revision_exhaustion_also_terminates(capsys) -> None:
    developer = _StubDeveloper()
    tester = _StubTester("passed")
    reviewer = _StubReviewer("revision")
    router = _router_with(developer=developer, tester=tester, reviewer=reviewer)

    workflow = TaskWorkflow(
        task_manager=_manager(),
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
        max_review_rounds=2,
    )

    result = workflow.execute("TASK-GATE-001")

    assert result.status == "failed"
    output = capsys.readouterr().out
    assert "[Gate] TASK-GATE-001 round 1/2: reviewer=revision" in output
    # 终态错误可能来自内部轮次守卫（英文）或外层耗尽兜底（中文），二者皆可。
    assert (
        "质量门禁" in (result.error or "")
        or "failed review" in (result.error or "").lower()
    )
