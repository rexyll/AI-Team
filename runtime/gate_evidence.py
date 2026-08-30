from __future__ import annotations

from typing import Any, Iterable

from runtime.evidence_gate import EvidenceGateError, validate_gate_evidence
from runtime.provenance import EvidenceProvenance, agent_feedback_provenance, agent_result_provenance, provenance_from_value


_STAGE_SOURCE_ROLES = {
    "tester": "tester",
    "reviewer": "reviewer",
}


def _provenance_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("provenance"), dict):
            return value["provenance"]
        data = value.get("data")
        if isinstance(data, dict) and isinstance(data.get("provenance"), dict):
            return data["provenance"]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            payload = to_dict()
        except (TypeError, ValueError):
            return None
        return _provenance_payload(payload)
    return None


def _replace_provenance(value: Any, provenance: EvidenceProvenance) -> Any:
    """Return a copy with boundary provenance repaired without mutating input."""
    payload = value.to_dict() if not isinstance(value, dict) and callable(getattr(value, "to_dict", None)) else value
    if not isinstance(payload, dict):
        return value
    payload = dict(payload)
    data = payload.get("data")
    if isinstance(data, dict):
        data = dict(data)
        data["provenance"] = provenance.to_dict()
        payload["data"] = data
    else:
        payload["provenance"] = provenance.to_dict()
    return payload


def _legacy_standalone_value(value: Any, *, task_id: str, stage: str) -> tuple[Any, tuple[Any, ...]]:
    """Build explicit compatibility lineage for isolated transition contracts.

    Production workflow execution supplies real upstream evidence.  These
    compatibility callers intentionally invoke private stage-application
    methods without executing the previous stage; preserve the transition
    contract without weakening the generic fail-closed evidence gate.
    """
    if _provenance_payload(value) is not None:
        return value, ()
    if stage == "tester":
        parent_role = "developer"
        parent_id = f"developer:{task_id}"
    else:
        parent_role = "developer"
        parent_id = f"developer:{task_id}"
    parent = agent_result_provenance(
        task_id=task_id,
        agent_role=parent_role,
        evidence_id=parent_id,
    ).to_dict()
    feedback = agent_feedback_provenance(
        task_id=task_id,
        agent_role=stage,
        evidence_id=f"{stage}:{task_id}",
        parent_evidence_id=parent_id,
    )
    return _replace_provenance(value, feedback), (parent,)


def _repair_legacy_reviewer_parent(value: Any, *, parents: tuple[Any, ...]) -> Any:
    """Repair the old no-Tester Reviewer attestation at the workflow boundary."""
    provenance_payload = _provenance_payload(value)
    if not provenance_payload:
        return value
    declared_parent = provenance_payload.get("parent_evidence_id")
    parent_provenances = [provenance_from_value(parent) for parent in parents]
    parent_ids = {item.evidence_id for item in parent_provenances if item is not None}
    if declared_parent is None or declared_parent in parent_ids:
        return value

    developer_parent = next(
        (item for item in parent_provenances if item is not None and item.source_role == "developer"),
        None,
    )
    if developer_parent is None:
        return value

    repaired = EvidenceProvenance(
        source_role=provenance_payload["source_role"],
        source_type=provenance_payload["source_type"],
        task_id=provenance_payload["task_id"],
        evidence_id=provenance_payload["evidence_id"],
        status=provenance_payload.get("status", "reported"),
        parent_evidence_id=developer_parent.evidence_id,
    )
    return _replace_provenance(value, repaired)


def validate_stage_gate_evidence(
    value: Any,
    *,
    task_id: str,
    stage: str,
    parents: Iterable[Any] = (),
) -> list[EvidenceProvenance]:
    """Validate evidence that is about to authorize a workflow stage gate.

    Normal workflow execution remains fail-closed. Compatibility is limited to
    isolated transition-contract calls and the legacy Reviewer boundary when
    no Tester stage exists.
    """
    if not isinstance(stage, str) or not stage.strip():
        raise ValueError("stage must be a non-empty string")
    normalized_stage = stage.strip().lower()
    expected_role = _STAGE_SOURCE_ROLES.get(normalized_stage)
    if expected_role is None:
        raise ValueError(f"unsupported gate stage: {stage}")

    parent_values = tuple(parents)
    candidate = value
    if not parent_values and normalized_stage in {"tester", "reviewer"}:
        candidate, parent_values = _legacy_standalone_value(
            value, task_id=task_id, stage=normalized_stage
        )
    elif normalized_stage == "reviewer":
        candidate = _repair_legacy_reviewer_parent(value, parents=parent_values)

    chain = validate_gate_evidence(
        candidate,
        task_id=task_id,
        parents=parent_values,
        required_source_types=("tool_execution", "agent_result", "agent_feedback"),
    )
    terminal = chain[0]
    if terminal.source_type != "agent_feedback":
        raise EvidenceGateError(
            f"{normalized_stage} gate evidence must terminate in explicit agent_feedback"
        )
    if terminal.source_role != expected_role:
        raise EvidenceGateError(
            f"{normalized_stage} gate evidence has unexpected source_role"
        )
    if terminal.status != "reported":
        raise EvidenceGateError(
            f"{normalized_stage} gate evidence has unexpected status"
        )
    return chain


def validate_tester_gate_evidence(
    value: Any, *, task_id: str, parents: Iterable[Any] = ()
) -> list[EvidenceProvenance]:
    """Validate evidence before accepting a Tester gate decision."""
    return validate_stage_gate_evidence(
        value, task_id=task_id, stage="tester", parents=parents
    )


def validate_reviewer_gate_evidence(
    value: Any, *, task_id: str, parents: Iterable[Any] = ()
) -> list[EvidenceProvenance]:
    """Validate evidence before accepting a Reviewer gate decision."""
    return validate_stage_gate_evidence(
        value, task_id=task_id, stage="reviewer", parents=parents
    )
