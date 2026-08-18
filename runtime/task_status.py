from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    REVIEW_PENDING = "review_pending"
    REVIEWING = "reviewing"
    REVISION = "revision"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


VALID_STATUS_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.READY,
        TaskStatus.BLOCKED,
    },
    TaskStatus.READY: {
        TaskStatus.RUNNING,
        TaskStatus.BLOCKED,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.REVIEW_PENDING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.REVISION,
    },
    TaskStatus.REVIEW_PENDING: {
        TaskStatus.REVIEWING,
        TaskStatus.FAILED,
    },
    TaskStatus.REVIEWING: {
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.REVISION,
    },
    TaskStatus.REVISION: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.BLOCKED: {
        TaskStatus.READY,
    },
}


def normalize_status(status: str | TaskStatus) -> TaskStatus:
    """Convert a string or TaskStatus into TaskStatus."""
    if isinstance(status, TaskStatus):
        return status

    try:
        return TaskStatus(status)
    except ValueError as exc:
        raise ValueError(f"Invalid task status: {status}") from exc


def can_transition(
    current: str | TaskStatus,
    target: str | TaskStatus,
) -> bool:
    """Return whether a task may transition from current to target."""
    current_status = normalize_status(current)
    target_status = normalize_status(target)

    return target_status in VALID_STATUS_TRANSITIONS[current_status]


def validate_transition(
    current: str | TaskStatus,
    target: str | TaskStatus,
) -> None:
    """Raise ValueError when a task status transition is invalid."""
    current_status = normalize_status(current)
    target_status = normalize_status(target)

    if not can_transition(current_status, target_status):
        raise ValueError(
            f"Invalid task status transition: "
            f"{current_status.value} -> {target_status.value}"
        )