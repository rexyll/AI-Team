import pytest

from runtime.retry_policy import FailureKind, decide_retry


def test_retry_is_allowed_before_budget_is_exhausted():
    decision = decide_retry(
        attempt=0,
        max_retries=2,
        failure_kind=FailureKind.EXECUTION,
        reason="temporary provider failure",
    )

    assert decision.retry is True
    assert decision.attempt == 1
    assert decision.max_retries == 2
    assert decision.failure_kind is FailureKind.EXECUTION
    assert decision.reason == "temporary provider failure"


def test_retry_is_denied_when_budget_is_exhausted():
    decision = decide_retry(
        attempt=2,
        max_retries=2,
        failure_kind=FailureKind.EXECUTION,
        reason="provider failure",
    )

    assert decision.retry is False
    assert decision.attempt == 2


def test_non_retryable_failure_denies_retry_even_with_budget():
    decision = decide_retry(
        attempt=0,
        max_retries=3,
        failure_kind=FailureKind.NON_RETRYABLE,
        reason="invalid credentials",
    )

    assert decision.retry is False
    assert decision.attempt == 0


def test_quality_gate_failure_is_retryable_when_budget_exists():
    decision = decide_retry(
        attempt=1,
        max_retries=3,
        failure_kind=FailureKind.QUALITY_GATE,
        reason="tests failed",
    )

    assert decision.retry is True
    assert decision.attempt == 2


def test_retry_policy_does_not_mutate_input_state():
    attempt = 1
    max_retries = 2

    decide_retry(
        attempt=attempt,
        max_retries=max_retries,
        failure_kind=FailureKind.EXECUTION,
        reason="temporary",
    )

    assert attempt == 1
    assert max_retries == 2


@pytest.mark.parametrize(
    "attempt,max_retries",
    [(-1, 1), (2, 1)],
)
def test_retry_policy_rejects_invalid_attempt_bounds(attempt, max_retries):
    with pytest.raises(ValueError):
        decide_retry(
            attempt=attempt,
            max_retries=max_retries,
            failure_kind=FailureKind.EXECUTION,
            reason="failure",
        )


def test_retry_policy_rejects_invalid_configuration_types():
    with pytest.raises(TypeError):
        decide_retry(
            attempt=True,
            max_retries=1,
            failure_kind=FailureKind.EXECUTION,
            reason="failure",
        )

    with pytest.raises(TypeError):
        decide_retry(
            attempt=0,
            max_retries=True,
            failure_kind=FailureKind.EXECUTION,
            reason="failure",
        )

    with pytest.raises(TypeError):
        decide_retry(
            attempt=0,
            max_retries=1,
            failure_kind="execution",
            reason="failure",
        )


def test_retry_policy_requires_reason():
    with pytest.raises(ValueError):
        decide_retry(
            attempt=0,
            max_retries=1,
            failure_kind=FailureKind.EXECUTION,
            reason="   ",
        )
