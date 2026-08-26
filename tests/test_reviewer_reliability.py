from agents.reviewer import ReviewerAgent
from runtime.agent_result import AgentResult
from runtime.reviewer_reliability import ResilientReviewerAgent


class _FakeReviewer:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def run(self, task):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _task():
    class TaskLike:
        id = "TASK-REVIEWER-001"

    return TaskLike()


def test_primary_reviewer_success_does_not_use_fallback():
    primary = _FakeReviewer(
        result=AgentResult(
            status="approved",
            agent="reviewer",
            task_id="TASK-REVIEWER-001",
            message="APPROVED",
        )
    )
    fallback = _FakeReviewer(
        result=AgentResult(
            status="approved",
            agent="reviewer",
            task_id="TASK-REVIEWER-001",
            message="APPROVED",
        )
    )

    wrapper = ResilientReviewerAgent(primary, fallback)
    result = wrapper.run(_task())

    assert result.status == "approved"
    assert result.data["reviewer_execution"]["source"] == "primary"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert wrapper.stats.primary_successes == 1
    assert wrapper.stats.fallback_attempts == 0


def test_primary_failure_recovers_with_fallback():
    primary = _FakeReviewer(error=ValueError("invalid reviewer decision"))
    fallback = _FakeReviewer(
        result=AgentResult(
            status="approved",
            agent="reviewer",
            task_id="TASK-REVIEWER-001",
            message="APPROVED",
        )
    )

    wrapper = ResilientReviewerAgent(primary, fallback)
    result = wrapper.run(_task())

    assert result.status == "approved"
    assert result.data["reviewer_execution"]["source"] == "fallback"
    assert result.data["reviewer_execution"]["recovered"] is True
    assert primary.calls == 1
    assert fallback.calls == 1
    assert wrapper.stats.primary_failures == 1
    assert wrapper.stats.fallback_successes == 1


def test_primary_and_fallback_failure_becomes_recovery_revision_not_exception():
    primary = _FakeReviewer(error=RuntimeError("primary unavailable"))
    fallback = _FakeReviewer(error=RuntimeError("fallback unavailable"))

    wrapper = ResilientReviewerAgent(primary, fallback)
    result = wrapper.run(_task())

    assert result.status == "revision"
    execution = result.data["reviewer_execution"]
    assert execution["source"] == "recovery"
    assert execution["recovered"] is False
    assert "primary unavailable" in execution["primary_error"]
    assert "fallback unavailable" in execution["fallback_error"]
    assert primary.calls == 1
    assert fallback.calls == 1
    assert wrapper.stats.primary_failures == 1
    assert wrapper.stats.fallback_attempts == 1
    assert wrapper.stats.fallback_failures == 1


def test_reliability_stats_are_serializable():
    primary = _FakeReviewer(error=ValueError("invalid reviewer decision"))
    fallback = _FakeReviewer(
        result=AgentResult(
            status="revision",
            agent="reviewer",
            task_id="TASK-REVIEWER-001",
            message="REVISION_REQUIRED",
        )
    )

    wrapper = ResilientReviewerAgent(primary, fallback)
    wrapper.run(_task())

    assert wrapper.stats.to_dict() == {
        "primary_attempts": 1,
        "primary_successes": 0,
        "primary_failures": 1,
        "fallback_attempts": 1,
        "fallback_successes": 1,
        "fallback_failures": 0,
        "empty_responses": 0,
    }
