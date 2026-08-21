from dataclasses import dataclass, field
from typing import Any


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

    def configure_retry(self, *, max_retries: int) -> None:
        if not isinstance(max_retries, int) or isinstance(max_retries, bool):
            raise TypeError("max_retries must be an integer")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_attempt > max_retries:
            raise ValueError("max_retries cannot be below current retry attempt")
        self.max_retries = max_retries

    def record_retry_attempt(self, *, reason: str, retryable: bool) -> None:
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
            result=dict(payload.get("result", {})),
            context=dict(payload.get("context", {})),
            review_result=dict(payload.get("review_result", {})),
            review_history=list(payload.get("review_history", [])),
            test_result=dict(payload.get("test_result", {})),
            test_history=list(payload.get("test_history", [])),
            retry_attempt=payload.get("retry_attempt", 0),
            max_retries=payload.get("max_retries", 0),
            retry_history=list(payload.get("retry_history", [])),
        )
        task.validate_contract()
        return task

    def validate_contract(self) -> None:
        from runtime.runtime_contract import validate_task_contract

        validate_task_contract(self)
