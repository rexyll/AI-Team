from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ContractError(ValueError):
    """Raised when a runtime object violates its public contract."""


class TaskContextKey(str, Enum):
    """Reserved keys stored in Task.context."""

    DEPENDENCIES = "dependencies"
    TESTER_FEEDBACK = "tester_feedback"
    REVIEWER_FEEDBACK = "reviewer_feedback"


class AgentResultStatus(str, Enum):
    """Canonical AgentResult statuses.

    This enum intentionally describes Agent-level outcomes,
    not Task lifecycle states.
    """

    COMPLETED = "completed"
    PASSED = "passed"
    FAILED = "failed"
    APPROVED = "approved"
    REVISION = "revision"


@dataclass(frozen=True)
class TaskFieldContract:
    name: str
    required: bool
    description: str


TASK_FIELD_CONTRACTS: tuple[TaskFieldContract, ...] = (
    TaskFieldContract(
        "id",
        True,
        "Unique task identifier.",
    ),
    TaskFieldContract(
        "title",
        True,
        "Human-readable task title.",
    ),
    TaskFieldContract(
        "description",
        True,
        "Task requirements and description.",
    ),
    TaskFieldContract(
        "role",
        True,
        "Primary role responsible for the task.",
    ),
    TaskFieldContract(
        "status",
        True,
        "Current Task lifecycle state.",
    ),
    TaskFieldContract(
        "dependencies",
        True,
        "Task IDs that must complete before this task.",
    ),
    TaskFieldContract(
        "result",
        True,
        "Latest successful task result.",
    ),
    TaskFieldContract(
        "context",
        True,
        "Execution context available to agents.",
    ),
    TaskFieldContract(
        "review_result",
        True,
        "Latest reviewer result.",
    ),
    TaskFieldContract(
        "review_history",
        True,
        "Historical reviewer results.",
    ),
    TaskFieldContract(
        "test_result",
        True,
        "Latest tester result.",
    ),
    TaskFieldContract(
        "test_history",
        True,
        "Historical tester results.",
    ),
    TaskFieldContract(
        "review_round",
        True,
        "Number of review decisions recorded.",
    ),
    TaskFieldContract(
        "error",
        True,
        "Latest task execution error, if any.",
    ),
)


def validate_task_contract(task: Any) -> None:
    """Validate the structural contract of a Task instance."""

    required_fields = {
        item.name
        for item in TASK_FIELD_CONTRACTS
        if item.required
    }

    missing = [
        field
        for field in required_fields
        if not hasattr(task, field)
    ]

    if missing:
        raise ContractError(
            "Task is missing required fields: "
            + ", ".join(sorted(missing))
        )

    if not isinstance(task.id, str) or not task.id:
        raise ContractError(
            "Task.id must be a non-empty string"
        )

    if not isinstance(task.title, str):
        raise ContractError(
            "Task.title must be a string"
        )

    if not isinstance(task.description, str):
        raise ContractError(
            "Task.description must be a string"
        )

    if not isinstance(task.role, str):
        raise ContractError(
            "Task.role must be a string"
        )

    if not isinstance(task.dependencies, list):
        raise ContractError(
            "Task.dependencies must be a list"
        )

    if not isinstance(task.context, dict):
        raise ContractError(
            "Task.context must be a dict"
        )

    if not isinstance(task.result, dict):
        raise ContractError(
            "Task.result must be a dict"
        )

    if not isinstance(task.review_result, dict):
        raise ContractError(
            "Task.review_result must be a dict"
        )

    if not isinstance(task.review_history, list):
        raise ContractError(
            "Task.review_history must be a list"
        )

    if not isinstance(task.test_result, dict):
        raise ContractError(
            "Task.test_result must be a dict"
        )

    if not isinstance(task.test_history, list):
        raise ContractError(
            "Task.test_history must be a list"
        )

    if not isinstance(task.review_round, int):
        raise ContractError(
            "Task.review_round must be an int"
        )

    if task.review_round < 0:
        raise ContractError(
            "Task.review_round must be >= 0"
        )

    if task.error is not None and not isinstance(
        task.error,
        str,
    ):
        raise ContractError(
            "Task.error must be a string or None"
        )


def validate_context_contract(
    context: dict[str, Any],
) -> None:
    """Validate the top-level Task.context contract."""

    if not isinstance(context, dict):
        raise ContractError(
            "Task.context must be a dict"
        )

    reserved_keys = {
        key.value
        for key in TaskContextKey
    }

    for key in reserved_keys:
        if key not in context:
            continue

        value = context[key]

        if value is None:
            raise ContractError(
                f"Task.context['{key}'] cannot be None"
            )


def validate_agent_result_payload(
    result: Any,
) -> None:
    """Validate a normalized AgentResult-like payload."""

    if hasattr(result, "to_dict"):
        result = result.to_dict()

    if not isinstance(result, dict):
        raise ContractError(
            "Agent result must be a dict or support to_dict()"
        )

    if "status" not in result:
        raise ContractError(
            "Agent result must contain 'status'"
        )

    status = result["status"]

    if isinstance(status, Enum):
        status = status.value

    if not isinstance(status, str) or not status:
        raise ContractError(
            "Agent result 'status' must be a non-empty string"
        )

    if "data" in result and result["data"] is not None:
        if not isinstance(result["data"], dict):
            raise ContractError(
                "Agent result 'data' must be a dict or None"
            )


def validate_stage_outcome_contract(
    outcome: Any,
) -> None:
    """Validate a StageOutcome-like object."""

    required_fields = (
        "stage",
        "status",
        "result",
        "exception",
    )

    for field_name in required_fields:
        if not hasattr(outcome, field_name):
            raise ContractError(
                "StageOutcome is missing required field "
                f"'{field_name}'"
            )

    if outcome.stage is None:
        raise ContractError(
            "StageOutcome.stage cannot be None"
        )

    if not isinstance(outcome.status, str):
        raise ContractError(
            "StageOutcome.status must be a string"
        )

    if outcome.result is not None:
        validate_agent_result_payload(
            outcome.result
        )

    if (
        outcome.exception is not None
        and not isinstance(outcome.exception, Exception)
    ):
        raise ContractError(
            "StageOutcome.exception must be Exception or None"
        )