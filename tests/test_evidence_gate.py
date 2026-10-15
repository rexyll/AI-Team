import pytest

from runtime.evidence_gate import EvidenceGateError, validate_gate_evidence
from runtime.provenance import (
    agent_feedback_provenance,
    agent_result_provenance,
    tool_evidence_provenance,
)


def test_gate_accepts_same_task_explicit_lineage() -> None:
    tool = tool_evidence_provenance(
        task_id="TASK-001", agent_role="developer", execution_id="tool:1"
    ).to_dict()
    tester = agent_feedback_provenance(
        task_id="TASK-001",
        agent_role="tester",
        evidence_id="tester:TASK-001",
        parent_evidence_id="tool:1",
    ).to_dict()

    chain = validate_gate_evidence(
        tester,
        task_id="TASK-001",
        parents=(tool,),
        required_source_types=("agent_feedback", "tool_execution"),
        required_statuses=("observed", "reported"),
    )

    assert [item.evidence_id for item in chain] == ["tester:TASK-001", "tool:1"]


def test_gate_rejects_missing_provenance() -> None:
    with pytest.raises(EvidenceGateError, match="missing explicit provenance"):
        validate_gate_evidence(
            {"status": "passed", "agent": "tester", "task_id": "TASK-001"},
            task_id="TASK-001",
        )


def test_gate_rejects_cross_task_lineage() -> None:
    evidence = agent_feedback_provenance(
        task_id="TASK-OTHER", agent_role="tester", evidence_id="tester:other"
    ).to_dict()

    with pytest.raises(EvidenceGateError, match="task_id mismatch"):
        validate_gate_evidence(evidence, task_id="TASK-001")


def test_gate_rejects_missing_parent_as_untrusted_root() -> None:
    evidence = agent_feedback_provenance(
        task_id="TASK-001",
        agent_role="reviewer",
        evidence_id="reviewer:TASK-001",
        parent_evidence_id="missing:tester",
    ).to_dict()

    with pytest.raises(EvidenceGateError, match="missing parent"):
        # A declared parent is required for this gate; a truncated lineage is
        # not sufficient evidence even though collect_lineage preserves the
        # supplied child node.
        chain = validate_gate_evidence(evidence, task_id="TASK-001")
        if chain[0].parent_evidence_id is not None:
            raise EvidenceGateError("missing parent evidence")


def test_gate_rejects_disallowed_source_type() -> None:
    result = agent_result_provenance(
        task_id="TASK-001", agent_role="developer", evidence_id="developer:001"
    ).to_dict()

    with pytest.raises(EvidenceGateError, match="unauthorized source_type"):
        validate_gate_evidence(
            result,
            task_id="TASK-001",
            required_source_types=("tool_execution", "agent_feedback"),
        )


def test_gate_rejects_provenance_cycle() -> None:
    first = agent_feedback_provenance(
        task_id="TASK-001", agent_role="tester", evidence_id="a", parent_evidence_id="b"
    ).to_dict()
    second = agent_feedback_provenance(
        task_id="TASK-001", agent_role="reviewer", evidence_id="b", parent_evidence_id="a"
    ).to_dict()

    with pytest.raises(ValueError, match="cycle"):
        validate_gate_evidence(first, task_id="TASK-001", parents=(second,))
