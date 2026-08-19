from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """
    Context passed to an Agent during task execution.

    The context is intentionally read-oriented:
    agents receive a snapshot of the relevant task state instead of
    directly depending on the Task object's internal structure.
    """

    task_id: str
    task_title: str
    task_description: str

    role: str

    status: str

    review_round: int = 0

    dependencies: list[str] = field(default_factory=list)

    task_result: dict[str, Any] = field(default_factory=dict)

    tester_feedback: dict[str, Any] = field(default_factory=dict)

    reviewer_feedback: dict[str, Any] = field(default_factory=dict)

    history: list[dict[str, Any]] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)