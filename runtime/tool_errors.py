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


class ToolExecutionError(RuntimeError):
    """Base exception for failures that occur while executing a Tool."""


class ToolTimeoutError(ToolExecutionError):
    """Raised when Tool execution exceeds its allowed time."""


def _safe_message(exc: BaseException) -> str:
    """Return a bounded, non-secret-facing message for a Tool error."""
    message = str(exc).strip()
    if not message:
        return "Tool execution failed"
    # Do not expose Python tracebacks or arbitrarily large provider/runtime data.
    return message[:500]


def classify_tool_exception(exc: BaseException) -> ToolError:
    """Map known Tool-layer exceptions to the stable error taxonomy."""
    # Local imports avoid coupling the error contract to optional Tool modules.
    from security.tool_permission import ToolPermissionError
    from security.workspace import WorkspaceSandboxError

    if isinstance(exc, ToolTimeoutError):
        return ToolError("TOOL_TIMEOUT", TIMEOUT, "Tool execution timed out")
    if isinstance(exc, ToolPermissionError):
        return ToolError("TOOL_PERMISSION_DENIED", PERMISSION, "Tool permission denied")
    if isinstance(exc, WorkspaceSandboxError):
        return ToolError("TOOL_SANDBOX_VIOLATION", SANDBOX, "Tool workspace access denied")

    # Argument validation is intentionally identified structurally by class
    # name so this module remains compatible with the existing validator
    # module location/API without creating an import cycle.
    if exc.__class__.__name__ == "ToolArgumentValidationError":
        return ToolError("TOOL_ARGUMENT_INVALID", ARGUMENT_VALIDATION, "Tool arguments are invalid")

    if isinstance(exc, ToolExecutionError):
        return ToolError("TOOL_EXECUTION_FAILED", RUNTIME, _safe_message(exc))

    return ToolError("TOOL_EXECUTION_FAILED", UNKNOWN, "Tool execution failed")
