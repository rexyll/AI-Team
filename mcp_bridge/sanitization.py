from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

_REDACTED = "[REDACTED]"

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(access[_-]?token\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(authorization\s*[:=]\s*)[^\s,;]+"),
)

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:key|token|secret|password|authorization|credential)"
)

# MCP child processes inherit only the host environment minus variables whose
# names strongly indicate credentials. Normal process/tooling variables such
# as PATH, TEMP, SystemRoot, and locale settings remain available.
_SENSITIVE_ENV_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:api[_-]?key|access[_-]?token|auth(?:entication|orization)?|"
    r"credential|password|passwd|secret|private[_-]?key|client[_-]?secret|"
    r"session[_-]?token|refresh[_-]?token)(?:$|_)"
)


def redact_secrets(value: Any) -> Any:
    """Return a recursively sanitized value safe for MCP telemetry/responses."""
    if isinstance(value, str):
        result = value
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub(lambda match: match.group(1) + _REDACTED, result)
        return result
    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED if _SENSITIVE_KEY_RE.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, set):
        return [redact_secrets(item) for item in value]
    return value


def sanitized_environment() -> dict[str, str]:
    """Return a child-process environment without credential-like variables."""
    return {
        key: value
        for key, value in os.environ.items()
        if not _SENSITIVE_ENV_KEY_RE.search(key)
    }


def redact_environment_values(value: str, environment: Mapping[str, str] | None = None) -> str:
    """Redact inherited secret values if they appear in tool output."""
    result = value
    source = environment if environment is not None else os.environ
    for key, secret in source.items():
        if _SENSITIVE_ENV_KEY_RE.search(key) and secret:
            result = result.replace(secret, _REDACTED)
    return redact_secrets(result)
