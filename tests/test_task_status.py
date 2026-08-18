import pytest

from runtime.task_status import (
    TaskStatus,
    can_transition,
    normalize_status,
    validate_transition,
)


def test_task_status_values():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.READY.value == "ready"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.REVIEW_PENDING.value == "review_pending"
    assert TaskStatus.REVIEWING.value == "reviewing"
    assert TaskStatus.REVISION.value == "revision"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.BLOCKED.value == "blocked"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", "ready"),
        ("pending", "blocked"),
        ("ready", "running"),
        ("running", "review_pending"),
        ("running", "completed"),
        ("running", "failed"),
        ("review_pending", "reviewing"),
        ("reviewing", "running"),
        ("reviewing", "completed"),
        ("reviewing", "failed"),
        ("revision", "running"),
        ("revision", "failed"),
        ("blocked", "ready"),
    ],
)
def test_valid_status_transitions(current, target):
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", "running"),
        ("pending", "completed"),
        ("ready", "completed"),
        ("ready", "reviewing"),
        ("running", "ready"),
        ("running", "reviewing"),
        ("review_pending", "completed"),
        ("review_pending", "running"),
        ("reviewing", "ready"),
        ("completed", "running"),
        ("completed", "failed"),
        ("failed", "running"),
        ("blocked", "completed"),
    ],
)
def test_invalid_status_transitions(current, target):
    assert not can_transition(current, target)


def test_normalize_status_from_string():
    assert normalize_status("running") is TaskStatus.RUNNING


def test_normalize_status_from_enum():
    assert normalize_status(TaskStatus.RUNNING) is TaskStatus.RUNNING


def test_normalize_status_rejects_unknown_status():
    with pytest.raises(ValueError, match="Invalid task status"):
        normalize_status("unknown")


def test_validate_transition_accepts_valid_transition():
    validate_transition(
        TaskStatus.RUNNING,
        TaskStatus.REVIEW_PENDING,
    )


def test_validate_transition_rejects_invalid_transition():
    with pytest.raises(
        ValueError,
        match="Invalid task status transition",
    ):
        validate_transition(
            TaskStatus.PENDING,
            TaskStatus.COMPLETED,
        )


def test_terminal_completed_state_has_no_outgoing_transition():
    assert not can_transition(
        TaskStatus.COMPLETED,
        TaskStatus.RUNNING,
    )


def test_terminal_failed_state_has_no_outgoing_transition():
    assert not can_transition(
        TaskStatus.FAILED,
        TaskStatus.RUNNING,
    )