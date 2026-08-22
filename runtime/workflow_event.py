from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any


def _json_safe(value: Any, *, field_name: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be JSON serializable") from exc


@dataclass(frozen=True)
class WorkflowEvent:
    """Immutable, provider-independent fact describing one workflow event."""

    event_id: str
    event_type: str
    project_id: str
    occurred_at: str
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_id", "event_type", "project_id", "occurred_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.task_id is not None and (
            not isinstance(self.task_id, str) or not self.task_id.strip()
        ):
            raise ValueError("task_id must be a non-empty string or None")
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dictionary")
        safe_payload = _json_safe(self.payload, field_name="payload")
        if not isinstance(safe_payload, dict):
            raise TypeError("payload must be a JSON object")
        object.__setattr__(self, "payload", deepcopy(safe_payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "project_id": self.project_id,
            "occurred_at": self.occurred_at,
            "task_id": self.task_id,
            "payload": deepcopy(self.payload),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowEvent":
        if not isinstance(payload, dict):
            raise TypeError("workflow event payload must be a dictionary")
        required = {
            "event_id",
            "event_type",
            "project_id",
            "occurred_at",
            "task_id",
            "payload",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"workflow event missing fields: {sorted(missing)}")
        return cls(
            event_id=payload["event_id"],
            event_type=payload["event_type"],
            project_id=payload["project_id"],
            occurred_at=payload["occurred_at"],
            task_id=payload["task_id"],
            payload=payload["payload"],
        )
