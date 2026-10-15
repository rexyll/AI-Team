from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.reviewer_metrics import project_reviewer_reliability


PROJECT = "PROJECT-METRICS-001"
TASK = "TASK-METRICS-001"


def _event(event_id, event_type, occurred_at, payload, task_id=TASK):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=PROJECT,
        task_id=task_id,
        occurred_at=occurred_at,
        payload=payload,
    )


def _result(status, execution, reliability):
    return {
        "stage": "reviewer",
        "status": status,
        "result": {
            "status": status,
            "agent": "reviewer",
            "task_id": TASK,
            "message": status,
            "data": {
                "reviewer_execution": execution,
                "reviewer_reliability": reliability,
            },
        },
        "exception": None,
    }


def test_metrics_use_latest_cumulative_snapshot_per_task():
    events = [
        _event(
            "EVENT-001",
            "reviewer_fallback",
            "2026-08-26T10:00:00Z",
            _result(
                "revision",
                {"source": "recovery", "recovered": False},
                {
                    "primary_attempts": 1,
                    "primary_successes": 0,
                    "primary_failures": 1,
                    "fallback_attempts": 1,
                    "fallback_successes": 1,
                    "fallback_failures": 0,
                    "empty_responses": 1,
                },
            ),
        ),
        _event(
            "EVENT-002",
            "reviewer_approved",
            "2026-08-26T10:01:00Z",
            {**_result(
                "approved",
                {"source": "fallback", "recovered": True},
                {
                    "primary_attempts": 2,
                    "primary_successes": 1,
                    "primary_failures": 1,
                    "fallback_attempts": 1,
                    "fallback_successes": 1,
                    "fallback_failures": 0,
                    "empty_responses": 1,
                },
            ), "status": "completed"},
        ),
    ]
    metrics = project_reviewer_reliability(events, project_id=PROJECT)

    assert metrics.primary_attempts == 2
    assert metrics.primary_successes == 1
    assert metrics.primary_failures == 1
    assert metrics.fallback_attempts == 1
    assert metrics.empty_responses == 1
    assert metrics.recovery_count == 1
    assert metrics.recovery_success_count == 1
    assert metrics.recovery_exhausted_count == 0
    assert metrics.primary_success_rate == 0.5
    assert metrics.fallback_activation_rate == 0.5
    assert metrics.fallback_recovery_success_rate == 1.0


def test_metrics_detect_recovery_exhaustion_without_retry():
    log = WorkflowEventLog()
    log.merge([
        _event(
            "EVENT-001",
            "reviewer_fallback",
            "2026-08-26T11:00:00Z",
            _result("revision", {"source": "recovery", "recovered": False}, {
                "primary_attempts": 1,
                "primary_successes": 0,
                "primary_failures": 1,
                "fallback_attempts": 1,
                "fallback_successes": 0,
                "fallback_failures": 1,
                "empty_responses": 1,
            }),
        ),
        _event(
            "EVENT-002",
            "task_failed",
            "2026-08-26T11:01:00Z",
            {"status": "failed", "error": "reviewer recovery exhausted"},
        ),
    ])

    metrics = project_reviewer_reliability(log, project_id=PROJECT)

    assert metrics.recovery_count == 1
    assert metrics.recovery_success_count == 0
    assert metrics.recovery_exhausted_count == 1
    assert metrics.fallback_failures == 1


def test_metrics_ignore_other_projects():
    other = WorkflowEvent(
        event_id="EVENT-OTHER",
        event_type="reviewer_fallback",
        project_id="OTHER",
        task_id=TASK,
        occurred_at="2026-08-26T12:00:00Z",
        payload=_result("revision", {"source": "recovery"}, {
            "primary_attempts": 99,
            "primary_successes": 99,
        }),
    )
    metrics = project_reviewer_reliability([other], project_id=PROJECT)
    assert metrics.primary_attempts == 0
    assert metrics.recovery_count == 0
