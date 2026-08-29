from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ARGUMENT_VALIDATION = "argument_validation"
PERMISSION = "permission"
SANDBOX = "sandbox"
RUNTIME = "runtime"
TIMEOUT = "timeout"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolError:
    """Stable, machine-readable description of a Tool failure."""

    code: str
    category: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "details": self.details,
        }


class ToolExecutionError(RuntimeError):
    """Base exception for failures that occur while executing a Tool."""


class ToolTimeoutError(ToolExecutionError):
    """Raised when Tool execution exceeds its allowed time."""


def _safe_message(exc: BaseException) -> str:
    """Return a bounded message without exposing tracebacks or large payloads."""
    message = str(exc).strip()
    if not message:
        return "Tool execution failed"
    return message[:500]


def classify_tool_exception(exc: BaseException) -> ToolError:
    """Map Tool-layer exceptions to a stable, machine-readable taxonomy."""
    from security.tool_permission import ToolPermissionError

    if isinstance(exc, ToolTimeoutError):
        return ToolError("TOOL_TIMEOUT", TIMEOUT, "Tool execution timed out")
    if isinstance(exc, ToolPermissionError):
        return ToolError("TOOL_PERMISSION_DENIED", PERMISSION, "Tool permission denied")

    if exc.__class__.__name__ == "ToolArgumentValidationError":
        return ToolError(
            "TOOL_ARGUMENT_INVALID",
            ARGUMENT_VALIDATION,
            "Tool arguments are invalid",
        )

    # WorkspaceSandbox currently raises PermissionError for containment
    # failures. Keep that implementation detail out of the public contract.
    if isinstance(exc, PermissionError) and "outside workspace" in str(exc).lower():
        return ToolError(
            "TOOL_SANDBOX_VIOLATION",
            SANDBOX,
            "Tool workspace access denied",
        )

    if isinstance(exc, ToolExecutionError):
        return ToolError("TOOL_EXECUTION_FAILED", RUNTIME, _safe_message(exc))

    return ToolError("TOOL_EXECUTION_FAILED", UNKNOWN, "Tool execution failed")