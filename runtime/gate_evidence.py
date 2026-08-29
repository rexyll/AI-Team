from __future__ import annotations

from typing import Any, Iterable

from runtime.evidence_gate import EvidenceGateError, validate_gate_evidence
from runtime.provenance import EvidenceProvenance


_STAGE_SOURCE_ROLES = {
    "tester": "tester",
    "reviewer": "reviewer",
}


def validate_stage_gate_evidence(
    value: Any,
    *,
    task_id: str,
    stage: str,
    parents: Iterable[Any] = (),
) -> list[EvidenceProvenance]:
    """Validate evidence that is about to authorize a workflow stage gate.

    This is deliberately stricter than generic provenance parsing: the
    terminal evidence must be explicit producer-supplied feedback from the
    stage whose decision is being consumed.  Earlier lineage nodes may be
    tool executions or agent results, but the terminal decision cannot be
    synthesized from a legacy result shape.
    """
    if not isinstance(stage, str) or not stage.strip():
        raise ValueError("stage must be a non-empty string")
    normalized_stage = stage.strip().lower()
    expected_role = _STAGE_SOURCE_ROLES.get(normalized_stage)
    if expected_role is None:
        raise ValueError(f"unsupported gate stage: {stage}")

    chain = validate_gate_evidence(
        value,
        task_id=task_id,
        parents=parents,
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
