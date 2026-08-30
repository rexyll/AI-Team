from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from security.secrets import redact_mapping
from runtime.tracing import get_current_span


_RESERVED = {"asctime", "levelname", "name", "pathname", "filename", "module", "lineno"}


def build_log_record(
    event: str,
    *,
    level: str = "INFO",
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSON-safe structured log record.

    When a trace span is active, the record is automatically correlated with
    that span. Trace identifiers are metadata, not application-controlled
    fields, so callers cannot spoof the correlation values.
    """
    if not isinstance(event, str) or not event.strip():
        raise ValueError("event must be a non-empty string")
    if not isinstance(level, str) or not level.strip():
        raise ValueError("level must be a non-empty string")
    if fields is not None and not isinstance(fields, Mapping):
        raise TypeError("fields must be a mapping or None")

    safe_fields = redact_mapping(dict(fields or {}))
    safe_fields = {key: value for key, value in safe_fields.items() if key not in _RESERVED}
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level.strip().upper(),
        "event": event.strip(),
        "fields": safe_fields,
    }
    current_span = get_current_span()
    if current_span is not None:
        record["trace_id"] = current_span.trace_id
        record["span_id"] = current_span.span_id
    try:
        json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError("structured log fields must be JSON serializable") from exc
    return record


class StructuredLogger:
    """Small provider-independent adapter over stdlib logging."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("ai_team")

    def log(self, event: str, *, level: str = "INFO", fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        record = build_log_record(event, level=level, fields=fields)
        self._logger.log(getattr(logging, record["level"], logging.INFO), json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        return record

    def info(self, event: str, *, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.log(event, level="INFO", fields=fields)

    def warning(self, event: str, *, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.log(event, level="WARNING", fields=fields)

    def error(self, event: str, *, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.log(event, level="ERROR", fields=fields)
