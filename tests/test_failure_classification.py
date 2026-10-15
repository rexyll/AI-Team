from __future__ import annotations

import pytest

from runtime.failure_classification import FailureClass, classify_failure


@pytest.mark.parametrize(
    ("category", "retryable", "repairable", "replan_required"),
    [
        (FailureClass.TRANSIENT, True, False, False),
        (FailureClass.TOOL, True, False, False),
        (FailureClass.TEST, False, True, False),
        (FailureClass.IMPLEMENTATION, False, True, False),
        (FailureClass.DEPENDENCY, False, True, False),
        (FailureClass.AGENT, False, True, False),
        (FailureClass.SPECIFICATION, False, False, True),
        (FailureClass.UNKNOWN, False, False, False),
    ],
)
def test_failure_classification_maps_recovery_capabilities(
    category, retryable, repairable, replan_required
):
    classification = classify_failure(failure_class=category, reason="observed failure")

    assert classification.failure_class is category
    assert classification.retryable is retryable
    assert classification.repairable is repairable
    assert classification.replan_required is replan_required
    assert classification.reason == "observed failure"


def test_failure_classification_accepts_string_category_and_serializes():
    classification = classify_failure(
        failure_class="specification", reason="acceptance criteria conflict"
    )

    assert classification.to_dict() == {
        "failure_class": "specification",
        "retryable": False,
        "repairable": False,
        "replan_required": True,
        "reason": "acceptance criteria conflict",
    }


def test_failure_classification_rejects_unknown_category_and_empty_reason():
    with pytest.raises(ValueError, match="Invalid failure class"):
        classify_failure(failure_class="not-a-category", reason="failure")

    with pytest.raises(ValueError, match="failure reason must not be empty"):
        classify_failure(failure_class=FailureClass.TEST, reason="  ")
