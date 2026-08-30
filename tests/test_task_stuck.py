from datetime import datetime, timedelta, timezone

import pytest

from runtime.task_liveness import TaskLiveness
from runtime.task_stuck import (
    StuckTaskClassifier,
    StuckTaskError,
    StuckTaskPolicy,
    TaskLivenessState,
)


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _record(heartbeat_age=0, progress_age=0):
    return TaskLiveness(
        "TASK-1",
        "worker-a",
        NOW - timedelta(seconds=heartbeat_age),
        NOW - timedelta(seconds=progress_age),
    )


def test_healthy_when_heartbeat_and_progress_are_fresh():
    assessment = StuckTaskClassifier(StuckTaskPolicy(30, 60)).classify(_record(5, 10), now=NOW)
    assert assessment.state is TaskLivenessState.HEALTHY
    assert not assessment.is_stuck


def test_no_progress_is_distinguished_from_heartbeat_stale():
    assessment = StuckTaskClassifier(StuckTaskPolicy(30, 60)).classify(_record(5, 60), now=NOW)
    assert assessment.state is TaskLivenessState.NO_PROGRESS


def test_heartbeat_stale_is_distinguished_from_no_progress():
    assessment = StuckTaskClassifier(StuckTaskPolicy(30, 60)).classify(_record(30, 10), now=NOW)
    assert assessment.state is TaskLivenessState.HEARTBEAT_STALE


def test_task_is_stuck_only_when_both_signals_are_stale():
    assessment = StuckTaskClassifier(StuckTaskPolicy(30, 60)).classify(_record(31, 61), now=NOW)
    assert assessment.state is TaskLivenessState.STUCK
    assert assessment.is_stuck


def test_invalid_policy_is_rejected():
    with pytest.raises(StuckTaskError):
        StuckTaskPolicy(0, 60)
