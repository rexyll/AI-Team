from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceProvenance:
    """Minimal chain-of-custody metadata for evidence crossing agent boundaries."""

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
        if self.parent_evidence_id is not None and not isinstance(self.parent_evidence_id, str):
            raise TypeError("parent_evidence_id must be a string or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_role": self.source_role,
            "source_type": self.source_type,
            "task_id": self.task_id,
            "evidence_id": self.evidence_id,
            "status": self.status,
            "parent_evidence_id": self.parent_evidence_id,
        }


def tool_evidence_provenance(*, task_id: str, agent_role: str, execution_id: str) -> EvidenceProvenance:
    return EvidenceProvenance(
        source_role=agent_role,
        source_type="tool_execution",
        task_id=task_id,
        evidence_id=execution_id,
        status="observed",
    )


def agent_feedback_provenance(*, task_id: str, agent_role: str, evidence_id: str) -> EvidenceProvenance:
    return EvidenceProvenance(
        source_role=agent_role,
        source_type="agent_feedback",
        task_id=task_id,
        evidence_id=evidence_id,
        status="reported",
    )
