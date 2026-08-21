import pytest

from runtime.task_status import TaskStatus
from runtime.workflow_transition import (
    WORKFLOW_STAGE_TRANSITIONS,
    WorkflowOutcomeKind,
    get_workflow_transition,
)


def test_every_stage_outcome_has_one_explicit_transition():
    keys = [
        (item.stage, item.outcome)
        for item in WORKFLOW_STAGE_TRANSITIONS
    ]

    assert len(keys) == len(set(keys))


def test_developer_success_moves_to_review_pending():
    transition = get_workflow_transition(
        "developer",
        WorkflowOutcomeKind.SUCCESS,
    )

    assert transition.source is TaskStatus.RUNNING
    assert transition.target is TaskStatus.REVIEW_PENDING


def test_developer_failure_moves_to_failed():
    for outcome in (
        WorkflowOutcomeKind.EXECUTION_FAILURE,
        WorkflowOutcomeKind.INVALID_RESULT,
    ):
        transition = get_workflow_transition("developer", outcome)
        assert transition.source is TaskStatus.RUNNING
        assert transition.target is TaskStatus.FAILED


def test_tester_success_moves_to_reviewing():
    transition = get_workflow_transition(
        "tester",
        WorkflowOutcomeKind.SUCCESS,
    )

    assert transition.source is TaskStatus.REVIEW_PENDING
    assert transition.target is TaskStatus.REVIEWING


def test_tester_quality_failure_returns_to_running():
    transition = get_workflow_transition(
        "tester",
        WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
    )

    assert transition.source is TaskStatus.REVIEW_PENDING
    assert transition.target is TaskStatus.RUNNING


def test_tester_execution_or_contract_failure_is_terminal_failure():
    for outcome in (
        WorkflowOutcomeKind.EXECUTION_FAILURE,
        WorkflowOutcomeKind.INVALID_RESULT,
    ):
        transition = get_workflow_transition("tester", outcome)
        assert transition.source is TaskStatus.REVIEW_PENDING
        assert transition.target is TaskStatus.FAILED


def test_reviewer_success_completes_task():
    transition = get_workflow_transition(
        "reviewer",
        WorkflowOutcomeKind.SUCCESS,
    )

    assert transition.source is TaskStatus.REVIEWING
    assert transition.target is TaskStatus.COMPLETED


def test_reviewer_revision_returns_to_running():
    transition = get_workflow_transition(
        "reviewer",
        WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
    )

    assert transition.source is TaskStatus.REVIEWING
    assert transition.target is TaskStatus.RUNNING


def test_reviewer_execution_or_contract_failure_is_terminal_failure():
    for outcome in (
        WorkflowOutcomeKind.EXECUTION_FAILURE,
        WorkflowOutcomeKind.INVALID_RESULT,
    ):
        transition = get_workflow_transition("reviewer", outcome)
        assert transition.source is TaskStatus.REVIEWING
        assert transition.target is TaskStatus.FAILED


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError, match="No workflow transition defined"):
        get_workflow_transition(
            "scheduler",
            WorkflowOutcomeKind.SUCCESS,
        )


def test_transition_contract_does_not_include_scheduler_or_retry_semantics():
    assert {
        item.stage
        for item in WORKFLOW_STAGE_TRANSITIONS
    } == {"developer", "tester", "reviewer"}
