from datetime import datetime, timedelta, timezone

import pytest

from runtime.task_liveness import LivenessError, TaskLivenessTracker


def test_start_records_heartbeat_and_progress_at_same_instant():
    tracker = TaskLivenessTracker()
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    record = tracker.start("TASK-1", "worker-a", now=now)

    assert record.last_heartbeat_at == now
    assert record.last_progress_at == now
    assert record.heartbeat_age(now=now + timedelta(seconds=2)) == timedelta(seconds=2)
    assert record.progress_age(now=now + timedelta(seconds=2)) == timedelta(seconds=2)


def test_heartbeat_advances_liveness_without_claiming_progress():
    tracker = TaskLivenessTracker()
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    tracker.start("TASK-1", "worker-a", now=t0)
    record = tracker.heartbeat("TASK-1", "worker-a", now=t0 + timedelta(seconds=5))

    assert record.last_heartbeat_at == t0 + timedelta(seconds=5)
    assert record.last_progress_at == t0


def test_progress_advances_both_heartbeat_and_progress():
    tracker = TaskLivenessTracker()
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    tracker.start("TASK-1", "worker-a", now=t0)
    record = tracker.progress("TASK-1", "worker-a", now=t0 + timedelta(seconds=5))

    assert record.last_heartbeat_at == t0 + timedelta(seconds=5)
    assert record.last_progress_at == t0 + timedelta(seconds=5)


def test_stale_boundary_is_inclusive_and_does_not_mutate_state():
    tracker = TaskLivenessTracker()
    t0 = datetime(2026, 8, 30, tzinfo=timezone.utc)
    record = tracker.start("TASK-1", "worker-a", now=t0)
    assert record.is_heartbeat_stale(now=t0 + timedelta(seconds=10), timeout_seconds=10)
    assert tracker.get("TASK-1") == record


def test_wrong_owner_cannot_heartbeat_or_mark_progress():
    tracker = TaskLivenessTracker()
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    tracker.start("TASK-1", "worker-a", now=now)

    with pytest.raises(LivenessError):
        tracker.heartbeat("TASK-1", "worker-b", now=now)
    with pytest.raises(LivenessError):
        tracker.progress("TASK-1", "worker-b", now=now)
