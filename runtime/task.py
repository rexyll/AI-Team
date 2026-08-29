from dataclasses import dataclass, field
from typing import Any

from runtime.cancellation import CancellationRequested, CancellationSnapshot, CancellationToken
from runtime.task_status import TaskStatus, validate_transition


@dataclass
class Task:
    id: str
    title: str
    description: str
    role: str

    status: str = "pending"
    status_history: list[dict[str, Any]] = field(
        default_factory=list
    )
    error: str | None = None
    review_round: int = 0

    dependencies: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    review_result: dict[str, Any] = field(default_factory=dict)
    review_history: list[dict[str, Any]] = field(default_factory=list)
    test_result: dict[str, Any] = field(default_factory=dict)
    test_history: list[dict[str, Any]] = field(default_factory=list)

    retry_attempt: int = 0
    max_retries: int = 0
    retry_history: list[dict[str, Any]] = field(default_factory=list)

    cancellation_requested: bool = False
    cancellation_reason: str | None = None
    _cancellation_token: CancellationToken = field(
        default_factory=CancellationToken,
        init=False,
        repr=False,
        compare=False,
    )

    def configure_retry(self, *, max_retries: int) -> None:
        if not isinstance(max_retries, int) or isinstance(max_retries, bool):
            raise TypeError("max_retries must be an integer")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_attempt > max_retries:
            raise ValueError("max_retries cannot be below current retry attempt")
        self.max_retries = max_retries

    def record_retry_attempt(self, *, reason: str, retryable: bool) -> None:
        if self.cancellation_requested:
            raise RuntimeError("cancelled task cannot create a retry attempt")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("retry reason must be a non-empty string")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean")
        if not retryable:
            raise RuntimeError("non-retryable failure cannot create a retry attempt")
        if self.retry_attempt >= self.max_retries:
            raise RuntimeError("retry budget exhausted")

        self.retry_attempt += 1
        self.retry_history.append(
            {
                "attempt": self.retry_attempt,
                "reason": reason,
                "retryable": retryable,
            }
        )

    def cancel(self, reason: str | None = None) -> CancellationSnapshot:
        """Request cooperative cancellation and move the task to CANCELLED.

        Cancellation is a control-plane outcome, not a task failure: it never
        writes ``error`` and never consumes retry budget. Repeated cancellation
        requests are idempotent and preserve the first reason.
        """
        snapshot = self._cancellation_token.request(reason)
        self.cancellation_requested = snapshot.requested
        self.cancellation_reason = snapshot.reason

        if self.status != TaskStatus.CANCELLED.value:
            validate_transition(self.status, TaskStatus.CANCELLED)
            previous = self.status
            self.status = TaskStatus.CANCELLED.value
            self.status_history.append(
                {
                    "from": previous,
                    "to": TaskStatus.CANCELLED.value,
                    "reason": snapshot.reason,
                }
            )
        return snapshot

    def cancellation_snapshot(self) -> CancellationSnapshot:
        return self._cancellation_token.snapshot()

    def raise_if_cancelled(self) -> None:
        self._cancellation_token.raise_if_requested()

    def to_dict(self) -> dict[str, Any]:
        """Return the Task's persistence-safe, JSON-friendly state."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "role": self.role,
            "status": self.status,
            "status_history": self.status_history,
            "error": self.error,
            "review_round": self.review_round,
            "dependencies": self.dependencies,
            "result": self.result,
            "context": self.context,
            "review_result": self.review_result,
            "review_history": self.review_history,
            "test_result": self.test_result,
            "test_history": self.test_history,
            "retry_attempt": self.retry_attempt,
            "max_retries": self.max_retries,
            "retry_history": self.retry_history,
            "cancellation_requested": self.cancellation_requested,
            "cancellation_reason": self.cancellation_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Task":
        """Restore a Task from a persistence-safe mapping."""
        if not isinstance(payload, dict):
            raise TypeError("Task payload must be a dictionary")

        required = ("id", "title", "description", "role")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(
                "Task payload missing required fields: " + ", ".join(missing)
            )

        def _mapping(key: str) -> dict[str, Any]:
            value = payload.get(key)
            if value is None:
                return {}
            return dict(value)

        task = cls(
            id=payload["id"],
            title=payload["title"],
            description=payload["description"],
            role=payload["role"],
            status=payload.get("status", "pending"),
            status_history=list(payload.get("status_history", [])),
            error=payload.get("error"),
            review_round=payload.get("review_round", 0),
            dependencies=list(payload.get("dependencies", [])),
            result=_mapping("result"),
            context=_mapping("context"),
            review_result=_mapping("review_result"),
            review_history=list(payload.get("review_history", [])),
            test_result=_mapping("test_result"),
            test_history=list(payload.get("test_history", [])),
            retry_attempt=payload.get("retry_attempt", 0),
            max_retries=payload.get("max_retries", 0),
            retry_history=list(payload.get("retry_history", [])),
            cancellation_requested=payload.get("cancellation_requested", False),
            cancellation_reason=payload.get("cancellation_reason"),
        )
        if task.cancellation_requested:
            if task.status != TaskStatus.CANCELLED.value:
                raise ValueError("cancelled Task payload must have cancelled status")
            task._cancellation_token.request(task.cancellation_reason)
        elif task.cancellation_reason is not None:
            raise ValueError("cancellation_reason requires cancellation_requested")
        task.validate_contract()
        return task

    def validate_contract(self) -> None:
        from runtime.runtime_contract import validate_task_contract

        validate_task_contract(self)