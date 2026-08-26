from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_query import WorkflowEventQueryService


PROJECT = "PROJECT-QUERY-METRICS"
TASK = "TASK-QUERY-METRICS"


def _event(event_id, event_type, occurred_at, payload):
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=PROJECT,
        task_id=TASK,
        occurred_at=occurred_at,
        payload=payload,
    )


def _result(status, source, recovered, reliability):
    return {
        "stage": "reviewer",
        "status": status,
        "result": {
            "status": status,
            "agent": "reviewer",
            "task_id": TASK,
            "message": status,
            "data": {
                "reviewer_execution": {"source": source, "recovered": recovered},
                "reviewer_reliability": reliability,
            },
        },
        "exception": None,
    }


def test_query_service_exposes_reviewer_metrics_without_changing_lifecycle_projection():
    log = WorkflowEventLog()
    log.merge([
        _event("EVENT-001", "reviewer_fallback", "2026-08-26T13:00:00Z", _result(
            "revision", "recovery", False,
            {
                "primary_attempts": 1,
                "primary_successes": 0,
                "primary_failures": 1,
                "fallback_attempts": 1,
                "fallback_successes": 1,
                "fallback_failures": 0,
                "empty_responses": 1,
            },
        )),
        _event("EVENT-002", "reviewer_approved", "2026-08-26T13:01:00Z", {
            **_result("approved", "fallback", True, {
                "primary_attempts": 2,
                "primary_successes": 1,
                "primary_failures": 1,
                "fallback_attempts": 1,
                "fallback_successes": 1,
                "fallback_failures": 0,
                "empty_responses": 1,
            }),
            "status": "completed",
        }),
    ])

    query = WorkflowEventQueryService.from_log(log, project_id=PROJECT)

    assert query.lifecycle(TASK) == "completed"
    assert query.reviewer_metrics.primary_attempts == 2
    assert query.reviewer_metrics.fallback_attempts == 1
    assert query.reviewer_metrics.recovery_count == 1
    assert query.reviewer_metrics.recovery_success_count == 1
    assert query.reviewer_metrics.to_dict()["primary_success_rate"] == 0.5
