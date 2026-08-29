from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from runtime.evidence_lineage import collect_lineage
from runtime.provenance import EvidenceProvenance, provenance_from_value


class EvidenceGateError(ValueError):
    """Raised when evidence cannot establish a trustworthy gate decision."""


def _has_explicit_provenance(value: Any) -> bool:
    """Return whether provenance was actually supplied by the producer."""
    if isinstance(value, EvidenceProvenance):
        return True
    if not isinstance(value, dict):
        return False
    if all(key in value for key in ("source_role", "source_type", "task_id", "evidence_id")):
        return True
    provenance = value.get("provenance")
    if isinstance(provenance, dict):
        return True
    data = value.get("data")
    return isinstance(data, dict) and isinstance(data.get("provenance"), dict)


def validate_gate_evidence(
    value: Any,
    *,
    task_id: str,
    parents: Iterable[Any] = (),
    required_source_types: Iterable[str] = (),
    required_statuses: Iterable[str] = (),
) -> list[EvidenceProvenance]:
    """Validate evidence before it is allowed to support a workflow gate.

    The validator is intentionally fail-closed. It accepts only explicit
    provenance, requires every lineage node to belong to the current task,
    requires declared parents to be resolvable, and optionally constrains
    source types/statuses represented by the chain.
    """
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")

    if not _has_explicit_provenance(value):
        raise EvidenceGateError("gate evidence is missing explicit provenance")

    root = provenance_from_value(value)
    if root is None:
        raise EvidenceGateError("gate evidence is missing explicit provenance")

    chain = collect_lineage(value, parents=parents)
    if not chain:
        raise EvidenceGateError("gate evidence produced an empty provenance lineage")

    if chain[-1].parent_evidence_id is not None:
        raise EvidenceGateError("gate evidence lineage has missing parent evidence")

    expected_task_id = task_id.strip()
    if any(item.task_id != expected_task_id for item in chain):
        raise EvidenceGateError("gate evidence provenance task_id mismatch")

    allowed_types = {item.strip() for item in required_source_types if isinstance(item, str) and item.strip()}
    if allowed_types and any(item.source_type not in allowed_types for item in chain):
        raise EvidenceGateError("gate evidence contains an unauthorized source_type")

    allowed_statuses = {item.strip() for item in required_statuses if isinstance(item, str) and item.strip()}
    if allowed_statuses and any(item.status not in allowed_statuses for item in chain):
        raise EvidenceGateError("gate evidence contains an unauthorized status")

    return chain
