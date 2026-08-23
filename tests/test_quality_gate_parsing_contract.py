"""Quality-gate parsing and observability contracts.

Real providers rarely answer with a bare verdict-first line: they reason
first, wrap the verdict in markdown, or state it at the end. The gate
parsers must accept those shapes while staying conservative on ambiguous
evidence, and workflow stage failures must surface the underlying
exception instead of a generic fallback message.
"""

from __future__ import annotations

import pytest

from agents.reviewer import ReviewerAgent
# Aliased so pytest's ``Test*`` collection rule does not try to collect
# the agent class from this test module (mirrors the smoke contract).
from agents.tester import TesterAgent as RuntimeTesterAgent
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.workflow import TaskWorkflow


# ---------------------------------------------------------------------------
# Tester verdict parsing
# ---------------------------------------------------------------------------


def test_tester_keeps_verdict_first_contract() -> None:
    assert RuntimeTesterAgent._parse_result("TEST_PASSED\nall tests pass") == "passed"
    assert RuntimeTesterAgent._parse_result("TEST_FAILED\nmissing edge case") == "failed"


def test_tester_accepts_markdown_wrapped_verdict() -> None:
    assert RuntimeTesterAgent._parse_result("**TEST_PASSED**\n原因：22 个用例全部通过") == "passed"
    assert RuntimeTesterAgent._parse_result("**TEST_FAILED**\n原因：边界条件未覆盖") == "failed"


def test_tester_accepts_verdict_after_reasoning() -> None:
    response = (
        "根据 Developer 提供的证据，新增模块的 8 个用例全部通过，\n"
        "且全量回归 22 个用例无失败，未发现未处理边界。\n\n"
        "TEST_PASSED\n"
        "证据充分，允许进入审核。"
    )
    assert RuntimeTesterAgent._parse_result(response) == "passed"


def test_tester_accepts_lowercase_verdict() -> None:
    assert RuntimeTesterAgent._parse_result("test_passed\nevidence sufficient") == "passed"
    assert RuntimeTesterAgent._parse_result("test_failed\nevidence insufficient") == "failed"


def test_tester_failure_signal_wins_on_conflict() -> None:
    response = (
        "部分 TEST_PASSED 用例存在，但整体存在未处理异常，\n"
        "因此结论为 TEST_FAILED。"
    )
    assert RuntimeTesterAgent._parse_result(response) == "failed"


def test_tester_rejects_response_without_verdict_token() -> None:
    with pytest.raises(ValueError, match="invalid decision"):
        RuntimeTesterAgent._parse_result("looks good to me")


# ---------------------------------------------------------------------------
# Reviewer verdict parsing
# ---------------------------------------------------------------------------


def test_reviewer_keeps_verdict_first_contract() -> None:
    assert ReviewerAgent._parse_review_result("APPROVED\nquality is acceptable") == "approved"
    assert (
        ReviewerAgent._parse_review_result("REVISION_REQUIRED\nnaming violates guide")
        == "revision"
    )


def test_reviewer_accepts_markdown_wrapped_verdict() -> None:
    assert ReviewerAgent._parse_review_result("**APPROVED**\n原因：实现符合设计") == "approved"
    assert (
        ReviewerAgent._parse_review_result("**REVISION_REQUIRED**\n原因：缺少错误处理")
        == "revision"
    )


def test_reviewer_accepts_verdict_after_reasoning() -> None:
    response = (
        "实现与架构设计一致，测试证据完整，未发现安全问题。\n\n"
        "APPROVED\n"
        "可以交付。"
    )
    assert ReviewerAgent._parse_review_result(response) == "approved"


def test_reviewer_revision_signal_wins_on_conflict() -> None:
    response = (
        "整体接近可交付，但存在一处必须修正的命名问题，\n"
        "虽然部分维度已 APPROVED 级别，仍需返工。REVISION_REQUIRED"
    )
    assert ReviewerAgent._parse_review_result(response) == "revision"


def test_reviewer_rejects_response_without_verdict_token() -> None:
    with pytest.raises(ValueError, match="invalid decision"):
        ReviewerAgent._parse_review_result("ship it")


# ---------------------------------------------------------------------------
# Workflow observability: tester stage failures must surface the exception
# ---------------------------------------------------------------------------


class _StubDeveloper:
    role = "developer"

    def run(self, task: Task) -> AgentResult:
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message="implementation done",
        )


class _StubReviewer:
    role = "reviewer"

    def run(self, task: Task) -> AgentResult:
        raise AssertionError("reviewer must not run when the tester fails")


class _ExplodingTester:
    role = "tester"

    def run(self, task: Task) -> AgentResult:
        raise RuntimeError("unexpected model output: verdict token missing")


def test_tester_stage_failure_surfaces_real_exception() -> None:
    task = Task(
        id="TASK-GATE-001",
        title="gate observability",
        description="tester exception must be visible in task error",
        role="developer",
        status="running",
    )
    task_manager = TaskManager([task])

    router = AgentRouter()
    developer = _StubDeveloper()
    reviewer = _StubReviewer()
    tester = _ExplodingTester()
    router.register("developer", developer)
    router.register("reviewer", reviewer)
    router.register("tester", tester)

    workflow = TaskWorkflow(
        task_manager=task_manager,
        developer=developer,
        reviewer=reviewer,
        agent_router=router,
        tester=tester,
    )

    workflow.execute("TASK-GATE-001")

    failed_task = task_manager.get_task("TASK-GATE-001")
    assert failed_task.status == "failed"
    assert failed_task.error is not None
    assert "Tester execution failed" in failed_task.error
    assert "unexpected model output: verdict token missing" in failed_task.error
