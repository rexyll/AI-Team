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

    def validate_contract(self) -> None:
        from runtime.runtime_contract import validate_task_contract

        validate_task_contract(self)
