from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SOURCE_TYPES = frozenset({"tool_execution", "agent_feedback"})


@dataclass(frozen=True)
class EvidenceProvenance:
    """Chain-of-custody metadata for evidence crossing agent boundaries."""

    source_role: str
    source_type: str
    task_id: str
    evidence_id: str
    status: str = "observed"
    parent_evidence_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_role", "source_type", "task_id", "evidence_id", "status"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported evidence source_type: {self.source_type}")
        if self.parent_evidence_id is not None and (
            not isinstance(self.parent_evidence_id, str) or not self.parent_evidence_id.strip()
        ):
            raise ValueError("parent_evidence_id must be a non-empty string or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_role": self.source_role,
            "source_type": self.source_type,
            "task_id": self.task_id,
            "evidence_id": self.evidence_id,
            "status": self.status,
            "parent_evidence_id": self.parent_evidence_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceProvenance":
        if not isinstance(payload, dict):
            raise TypeError("evidence provenance payload must be a dictionary")
        required = ("source_role", "source_type", "task_id", "evidence_id")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError("evidence provenance missing fields: " + ", ".join(missing))
        return cls(
            source_role=payload["source_role"],
            source_type=payload["source_type"],
            task_id=payload["task_id"],
            evidence_id=payload["evidence_id"],
            status=payload.get("status", "observed"),
            parent_evidence_id=payload.get("parent_evidence_id"),
        )


def tool_evidence_provenance(
    *, task_id: str, agent_role: str, execution_id: str, parent_evidence_id: str | None = None
) -> EvidenceProvenance:
    return EvidenceProvenance(
        source_role=agent_role,
        source_type="tool_execution",
        task_id=task_id,
        evidence_id=execution_id,
        status="observed",
        parent_evidence_id=parent_evidence_id,
    )


def agent_feedback_provenance(
    *, task_id: str, agent_role: str, evidence_id: str, parent_evidence_id: str | None = None
) -> EvidenceProvenance:
    return EvidenceProvenance(
        source_role=agent_role,
        source_type="agent_feedback",
        task_id=task_id,
        evidence_id=evidence_id,
        status="reported",
        parent_evidence_id=parent_evidence_id,
    )


def provenance_from_value(value: Any) -> EvidenceProvenance | None:
    """Extract provenance from a canonical result/feedback payload."""
    if not isinstance(value, dict):
        return None
    candidates = [value.get("provenance")]
    data = value.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("provenance"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            try:
                return EvidenceProvenance.from_dict(candidate)
            except (TypeError, ValueError):
                continue
    return None
