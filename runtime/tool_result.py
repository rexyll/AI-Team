from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.tool_errors import ToolError, classify_tool_exception


@dataclass(frozen=True)
class ToolResult:
    """Stable result envelope for Tool execution."""

    success: bool
    output: Any = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if self.success and self.error is not None:
            raise ValueError("Successful ToolResult cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("Failed ToolResult must contain an error")

    @classmethod
    def ok(cls, output: Any = None) -> "ToolResult":
        return cls(success=True, output=output)

    @classmethod
    def fail(cls, error: ToolError) -> "ToolResult":
        if not isinstance(error, ToolError):
            raise TypeError("ToolResult.fail requires a ToolError")
        return cls(success=False, error=error)

    @classmethod
    def from_exception(cls, exc: BaseException) -> "ToolResult":
        return cls.fail(classify_tool_exception(exc))

    def to_dict(self) -> dict[str, Any]:
        """Return a provider-independent, JSON-friendly representation."""
        if self.success:
            return {"success": True, "output": self.output, "error": None}

        assert self.error is not None
        return {
            "success": False,
            "output": None,
            "error": {
                "code": self.error.code,
                "category": self.error.category,
                "message": self.error.message,
                "details": self.error.details,
            },
        }
