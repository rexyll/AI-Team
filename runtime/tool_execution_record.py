from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar
import json


_ALLOWED_STATUS: tuple[str, ...] = (
    "completed",
    "failed",
    "invalid_arguments",
    "unknown_tool",
)


def _json_safe(value: Any, *, field_name: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be JSON serializable") from exc


@dataclass(frozen=True)
class ToolExecutionRecord:
    """Immutable, persistence-safe facts about one tool invocation."""

    execution_id: str
    task_id: str
    agent_role: str
    tool_name: str
    started_at: str
    completed_at: str | None
    status: str
    arguments: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _allowed_status: ClassVar[tuple[str, ...]] = _ALLOWED_STATUS

    def __post_init__(self) -> None:
        for name in (
            "execution_id",
            "task_id",
            "agent_role",
            "tool_name",
            "started_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        if self.completed_at is not None and not isinstance(self.completed_at, str):
            raise TypeError("completed_at must be a string or None")
        if self.status not in self._allowed_status:
            raise ValueError(f"invalid tool execution status: {self.status}")
        if not isinstance(self.arguments, dict):
            raise TypeError("arguments must be a dictionary")
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")

        safe_arguments = _json_safe(self.arguments, field_name="arguments")
        safe_output = _json_safe(self.output, field_name="output")
        safe_error = _json_safe(self.error, field_name="error")
        safe_metadata = _json_safe(self.metadata, field_name="metadata")

        if not isinstance(safe_arguments, dict):
            raise TypeError("arguments must be a JSON object")
        if not isinstance(safe_metadata, dict):
            raise TypeError("metadata must be a JSON object")

        object.__setattr__(self, "arguments", deepcopy(safe_arguments))
        object.__setattr__(self, "output", deepcopy(safe_output))
        object.__setattr__(self, "error", deepcopy(safe_error))
        object.__setattr__(self, "metadata", deepcopy(safe_metadata))

        if self.status == "completed" and self.error is not None:
            raise ValueError("completed tool execution cannot contain an error")
        if self.status != "completed" and self.error is None:
            raise ValueError("non-completed tool execution must contain an error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "agent_role": self.agent_role,
            "tool_name": self.tool_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "arguments": deepcopy(self.arguments),
            "output": deepcopy(self.output),
            "error": deepcopy(self.error),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolExecutionRecord":
        if not isinstance(payload, dict):
            raise TypeError("tool execution record payload must be a dictionary")

        required = {
            "execution_id",
            "task_id",
            "agent_role",
            "tool_name",
            "started_at",
            "completed_at",
            "status",
            "arguments",
            "output",
            "error",
            "metadata",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(
                f"tool execution record missing fields: {sorted(missing)}"
            )
        return cls(**{key: payload[key] for key in required})
