from runtime.task_status import TaskStatus
from runtime.workflow_transition import WorkflowOutcomeKind, get_workflow_transition


def test_reviewer_execution_recovery_moves_reviewing_to_review_pending():
    transition = get_workflow_transition(
        "reviewer", WorkflowOutcomeKind.REVIEWER_RECOVERY
    )

    assert transition.source == TaskStatus.REVIEWING
    assert transition.target == TaskStatus.REVIEW_PENDING


def test_reviewer_retry_moves_review_pending_back_to_reviewing():
    transition = get_workflow_transition(
        "reviewer", WorkflowOutcomeKind.REVIEWER_RETRY
    )

    assert transition.source == TaskStatus.REVIEW_PENDING
    assert transition.target == TaskStatus.REVIEWING
