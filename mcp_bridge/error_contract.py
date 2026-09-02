from __future__ import annotations

from typing import Any

from .sanitization import redact_secrets


_ERROR_CATEGORIES = {
    "configuration": "configuration_error",
    "policy": "policy_denied",
    "request": "invalid_request",
    "execution": "execution_error",
    "not_found": "not_found",
}
_VALID_CATEGORIES = frozenset((*_ERROR_CATEGORIES.values(), "bridge_error"))


def normalize_error(exc: BaseException) -> dict[str, Any]:
    """Convert an MCP-facing exception into a stable, non-sensitive shape."""
    category = getattr(exc, "error_category", None)
    if not isinstance(category, str) or category not in _VALID_CATEGORIES:
        name = type(exc).__name__.lower()
        if "permission" in name or "policy" in name:
            category = _ERROR_CATEGORIES["policy"]
        elif "timeout" in name:
            category = _ERROR_CATEGORIES["execution"]
        elif isinstance(exc, FileNotFoundError):
            category = _ERROR_CATEGORIES["not_found"]
        elif isinstance(exc, (ValueError, TypeError)):
            category = _ERROR_CATEGORIES["request"]
        else:
            category = "bridge_error"
    return {
        "category": category,
        "type": type(exc).__name__,
        "message": redact_secrets(str(exc)),
    }
