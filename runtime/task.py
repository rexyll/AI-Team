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
    
    def validate_contract(self) -> None:
        from runtime.runtime_contract import validate_task_contract

        validate_task_contract(self)
