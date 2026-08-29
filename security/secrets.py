"""Secret-isolation primitives for agent-visible and persisted data."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


_SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|password|passwd|token|authorization|credential)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?P<prefix>\b(?:api[_-]?key|secret|password|passwd|token|authorization|credential)\s*[=:]\s*)"
    r"(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)

REDACTED = "[REDACTED]"


def is_secret_key(key: object) -> bool:
    """Return whether a mapping key should never expose its value."""
    return isinstance(key, str) and bool(_SECRET_KEY_PATTERN.search(key))


def redact_text(value: str) -> str:
    """Redact common secret assignments from text without changing safe text."""
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return _SECRET_VALUE_PATTERN.sub(r"\g<prefix>" + REDACTED, value)


def redact_value(value: Any) -> Any:
    """Return a detached value safe for agent context, logs, and persistence."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            key: REDACTED if is_secret_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, set):
        return {redact_value(item) for item in value}
    return deepcopy(value)


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Redact a mapping before it crosses an agent-visible/persistent boundary."""
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return redact_value(value)
