from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from runtime.task_status import TaskStatus


class WorkflowOutcomeKind(str, Enum):
    """Semantic outcome categories used by TaskWorkflow."""

    SUCCESS = "success"
    QUALITY_GATE_FAILURE = "quality_gate_failure"
    EXECUTION_FAILURE = "execution_failure"
    INVALID_RESULT = "invalid_result"


@dataclass(frozen=True)
class WorkflowTransition:
    """Declarative state transition owned by a workflow stage."""

    stage: str
    outcome: WorkflowOutcomeKind
    source: TaskStatus
    target: TaskStatus


# Phase 6.1 contract: stage outcomes have one explicit lifecycle target.
# Review-round limits are deliberately handled by TaskWorkflow and are not
# encoded here because they are policy, not state-machine topology.
WORKFLOW_STAGE_TRANSITIONS: tuple[WorkflowTransition, ...] = (
    WorkflowTransition(
        "developer",
        WorkflowOutcomeKind.SUCCESS,
        TaskStatus.RUNNING,
        TaskStatus.REVIEW_PENDING,
    ),
    WorkflowTransition(
        "developer",
        WorkflowOutcomeKind.EXECUTION_FAILURE,
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    ),
    WorkflowTransition(
        "developer",
        WorkflowOutcomeKind.INVALID_RESULT,
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    ),
    WorkflowTransition(
        "tester",
        WorkflowOutcomeKind.SUCCESS,
        TaskStatus.REVIEW_PENDING,
        TaskStatus.REVIEWING,
    ),
    WorkflowTransition(
        "tester",
        WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
        TaskStatus.REVIEW_PENDING,
        TaskStatus.RUNNING,
    ),
    WorkflowTransition(
        "tester",
        WorkflowOutcomeKind.EXECUTION_FAILURE,
        TaskStatus.REVIEW_PENDING,
        TaskStatus.FAILED,
    ),
    WorkflowTransition(
        "tester",
        WorkflowOutcomeKind.INVALID_RESULT,
        TaskStatus.REVIEW_PENDING,
        TaskStatus.FAILED,
    ),
    WorkflowTransition(
        "reviewer",
        WorkflowOutcomeKind.SUCCESS,
        TaskStatus.REVIEWING,
        TaskStatus.COMPLETED,
    ),
    WorkflowTransition(
        "reviewer",
        WorkflowOutcomeKind.QUALITY_GATE_FAILURE,
        TaskStatus.REVIEWING,
        TaskStatus.RUNNING,
    ),
    WorkflowTransition(
        "reviewer",
        WorkflowOutcomeKind.EXECUTION_FAILURE,
        TaskStatus.REVIEWING,
        TaskStatus.FAILED,
    ),
    WorkflowTransition(
        "reviewer",
        WorkflowOutcomeKind.INVALID_RESULT,
        TaskStatus.REVIEWING,
        TaskStatus.FAILED,
    ),
)


_TRANSITION_INDEX = {
    (item.stage, item.outcome): item
    for item in WORKFLOW_STAGE_TRANSITIONS
}


def get_workflow_transition(
    stage: str,
    outcome: WorkflowOutcomeKind,
) -> WorkflowTransition:
    """Return the explicit lifecycle transition for a stage outcome."""

    if not isinstance(stage, str) or not stage.strip():
        raise TypeError("stage must be a non-empty string")

    if not isinstance(outcome, WorkflowOutcomeKind):
        raise TypeError("outcome must be a WorkflowOutcomeKind")

    try:
        return _TRANSITION_INDEX[(stage.strip(), outcome)]
    except KeyError as exc:
        raise ValueError(
            f"No workflow transition defined for stage={stage!r}, "
            f"outcome={outcome.value!r}"
        ) from exc
