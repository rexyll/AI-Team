from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolInvocation:
    """Immutable request passed to the canonical tool invocation boundary."""

    role: str
    task_id: str
    execution_id: str
    tool_name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("role", "task_id", "execution_id", "tool_name"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))

    def as_dict(self) -> dict[str, Any]:
        """Return a detached mutable representation for registry/tool validation."""
        return dict(self.arguments)

    @classmethod
    def from_dict(cls, invocation: Mapping[str, Any], *, role: str, task_id: str) -> "ToolInvocation":
        if not isinstance(invocation, Mapping):
            raise TypeError("each invocation must be a mapping")
        missing = {"execution_id", "tool_name", "arguments"} - invocation.keys()
        if missing:
            raise ValueError("invocation is missing required fields: " + ", ".join(sorted(missing)))
        return cls(
            role=role,
            task_id=task_id,
            execution_id=str(invocation["execution_id"]),
            tool_name=str(invocation["tool_name"]),
            arguments=invocation["arguments"],
        )
