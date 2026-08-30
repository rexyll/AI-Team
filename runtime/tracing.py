from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Iterator, Mapping
from uuid import uuid4

from security.secrets import redact_mapping


_current_span: ContextVar["TraceSpan | None"] = ContextVar("ai_team_current_span", default=None)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("span name must be a non-empty string")
    return name.strip()


def _safe_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    if attributes is not None and not isinstance(attributes, Mapping):
        raise TypeError("attributes must be a mapping or None")
    safe = redact_mapping(dict(attributes or {}))
    try:
        json.dumps(safe, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError("trace attributes must be JSON serializable") from exc
    return safe


@dataclass
class TraceSpan:
    """One provider-independent tracing span."""

    name: str
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid4().hex)
    parent_span_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=_timestamp)
    ended_at: str | None = None
    status: str = "unset"
    error: str | None = None
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        self.name = _validate_name(self.name)
        if not isinstance(self.trace_id, str) or not self.trace_id.strip():
            raise ValueError("trace_id must be a non-empty string")
        if not isinstance(self.span_id, str) or not self.span_id.strip():
            raise ValueError("span_id must be a non-empty string")
        if self.parent_span_id is not None and not isinstance(self.parent_span_id, str):
            raise TypeError("parent_span_id must be a string or None")
        self.attributes = _safe_attributes(self.attributes)
        if self.status not in {"unset", "ok", "error"}:
            raise ValueError("span status must be unset, ok, or error")

    def set_attribute(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("trace attribute names must be non-empty strings")
        candidate = dict(self.attributes)
        candidate[key.strip()] = value
        self.attributes = _safe_attributes(candidate)

    def set_status(self, status: str) -> None:
        if status not in {"unset", "ok", "error"}:
            raise ValueError("span status must be unset, ok, or error")
        self.status = status

    def finish(self, *, status: str | None = None, error: str | None = None) -> "TraceSpan":
        if self.ended_at is not None:
            return self
        if status is not None:
            self.set_status(status)
        if error is not None:
            if not isinstance(error, str):
                raise TypeError("span error must be a string or None")
            self.error = error
            self.status = "error"
        self.duration_seconds = max(0.0, monotonic() - getattr(self, "_started_monotonic", monotonic()))
        self.ended_at = _timestamp()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error": self.error,
            "attributes": dict(self.attributes),
        }


class Tracer:
    """Small thread/context-safe tracer with detached in-process snapshots."""

    def __init__(self) -> None:
        self._completed: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        parent: TraceSpan | None = None,
        trace_id: str | None = None,
    ) -> TraceSpan:
        name = _validate_name(name)
        current = parent if parent is not None else _current_span.get()
        if current is not None:
            resolved_trace_id = current.trace_id
            parent_span_id = current.span_id
        else:
            resolved_trace_id = trace_id or uuid4().hex
            parent_span_id = None
        span = TraceSpan(
            name=name,
            trace_id=resolved_trace_id,
            parent_span_id=parent_span_id,
            attributes=_safe_attributes(attributes),
        )
        span._started_monotonic = monotonic()
        return span

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        parent: TraceSpan | None = None,
        trace_id: str | None = None,
    ) -> Iterator[TraceSpan]:
        span = self.start_span(name, attributes=attributes, parent=parent, trace_id=trace_id)
        token = _current_span.set(span)
        try:
            yield span
        except Exception as exc:
            span.finish(status="error", error=type(exc).__name__)
            raise
        else:
            span.finish(status="ok")
        finally:
            _current_span.reset(token)
            with self._lock:
                self._completed.append(span.to_dict())

    def record(self, span: TraceSpan) -> dict[str, Any]:
        if not isinstance(span, TraceSpan):
            raise TypeError("span must be a TraceSpan")
        span.finish()
        record = span.to_dict()
        with self._lock:
            self._completed.append(dict(record))
        return record

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    **record,
                    "attributes": dict(record["attributes"]),
                }
                for record in self._completed
            ]

    def reset(self) -> None:
        with self._lock:
            self._completed.clear()


DEFAULT_TRACER = Tracer()


def get_current_span() -> TraceSpan | None:
    """Return the current context-local span, if one is active."""
    return _current_span.get()


def get_current_trace_id() -> str | None:
    span = _current_span.get()
    return span.trace_id if span is not None else None
