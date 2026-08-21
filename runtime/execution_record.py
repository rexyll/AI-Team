from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar
import copy
import json


_ALLOWED_STATUS: tuple[str, ...] = ("running", "completed", "failed", "cancelled")
_ALLOWED_OUTCOME: tuple[str, ...] = ("success", "failure", "cancelled")


def _validate_json_safe(value: Any, *, field_name: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be JSON serializable") from exc


@dataclass(frozen=True)
class AgentExecutionRecord:
    """Immutable, persistence-safe facts about one agent execution."""

    execution_id: str
    project_id: str
    task_id: str
    agent_role: str
    stage: str
    attempt: int
    started_at: str
    completed_at: str | None
    status: str
    outcome: str | None
    result: Any = None
    error: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _allowed_status: ClassVar[tuple[str, ...]] = _ALLOWED_STATUS
    _allowed_outcome: ClassVar[tuple[str, ...]] = _ALLOWED_OUTCOME

    def __post_init__(self) -> None:
        for name in ("execution_id", "project_id", "task_id", "agent_role", "stage", "started_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool):
            raise TypeError("attempt must be an integer")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")

        if self.completed_at is not None and not isinstance(self.completed_at, str):
            raise TypeError("completed_at must be a string or None")
        if self.status not in self._allowed_status:
            raise ValueError(f"invalid status: {self.status}")
        if self.outcome is not None and self.outcome not in self._allowed_outcome:
            raise ValueError(f"invalid outcome: {self.outcome}")
        if self.status == "completed" and self.outcome is None:
            raise ValueError("completed execution must have an outcome")

        safe_result = _validate_json_safe(self.result, field_name="result")
        safe_error = _validate_json_safe(self.error, field_name="error")
        safe_metadata = _validate_json_safe(self.metadata, field_name="metadata")
        if not isinstance(safe_metadata, dict):
            raise TypeError("metadata must be a JSON object")

        object.__setattr__(self, "result", copy.deepcopy(safe_result))
        object.__setattr__(self, "error", copy.deepcopy(safe_error))
        object.__setattr__(self, "metadata", copy.deepcopy(safe_metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "agent_role": self.agent_role,
            "stage": self.stage,
            "attempt": self.attempt,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "outcome": self.outcome,
            "result": copy.deepcopy(self.result),
            "error": copy.deepcopy(self.error),
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentExecutionRecord":
        if not isinstance(payload, dict):
            raise TypeError("execution record payload must be a dictionary")
        required = {
            "execution_id", "project_id", "task_id", "agent_role", "stage",
            "attempt", "started_at", "completed_at", "status", "outcome",
            "result", "error", "metadata",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"execution record missing fields: {sorted(missing)}")
        return cls(**{key: payload[key] for key in required})
