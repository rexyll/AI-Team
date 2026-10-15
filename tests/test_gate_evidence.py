import pytest

from runtime.gate_evidence import (
    validate_reviewer_gate_evidence,
    validate_tester_gate_evidence,
)
from runtime.provenance import (
    agent_feedback_provenance,
    agent_result_provenance,
    tool_evidence_provenance,
)
from runtime.evidence_gate import EvidenceGateError


def _tester_chain():
    tool = tool_evidence_provenance(
        task_id="TASK-001", agent_role="developer", execution_id="tool:1"
    ).to_dict()
    tester = agent_feedback_provenance(
        task_id="TASK-001",
        agent_role="tester",
        evidence_id="tester:TASK-001",
        parent_evidence_id="tool:1",
    ).to_dict()
    return tester, (tool,)


def _reviewer_chain():
    tester, tester_parents = _tester_chain()
    reviewer = agent_feedback_provenance(
        task_id="TASK-001",
        agent_role="reviewer",
        evidence_id="reviewer:TASK-001:round:1",
        parent_evidence_id="tester:TASK-001",
    ).to_dict()
    return reviewer, (tester, *tester_parents)


def test_tester_gate_accepts_explicit_feedback_with_complete_lineage():
    value, parents = _tester_chain()
    chain = validate_tester_gate_evidence(value, task_id="TASK-001", parents=parents)
    assert [item.evidence_id for item in chain] == ["tester:TASK-001", "tool:1"]


def test_reviewer_gate_accepts_explicit_feedback_with_complete_lineage():
    value, parents = _reviewer_chain()
    chain = validate_reviewer_gate_evidence(value, task_id="TASK-001", parents=parents)
    assert [item.evidence_id for item in chain] == [
        "reviewer:TASK-001:round:1",
        "tester:TASK-001",
        "tool:1",
    ]


def test_tester_gate_rejects_synthesized_legacy_agent_result():
    value = {
        "agent": "tester",
        "task_id": "TASK-001",
        "status": "passed",
    }
    with pytest.raises(EvidenceGateError, match="missing explicit provenance"):
        validate_tester_gate_evidence(value, task_id="TASK-001")


def test_reviewer_gate_rejects_wrong_terminal_role():
    value = agent_feedback_provenance(
        task_id="TASK-001",
        agent_role="tester",
        evidence_id="tester:TASK-001",
    ).to_dict()
    with pytest.raises(EvidenceGateError, match="unexpected source_role"):
        validate_reviewer_gate_evidence(value, task_id="TASK-001")


def test_stage_gate_rejects_non_feedback_terminal_evidence():
    value = agent_result_provenance(
        task_id="TASK-001", agent_role="tester", evidence_id="tester-result"
    ).to_dict()
    with pytest.raises(EvidenceGateError, match="agent_feedback"):
        validate_tester_gate_evidence(value, task_id="TASK-001")


def test_reviewer_gate_rejects_cross_task_parent():
    reviewer = agent_feedback_provenance(
        task_id="TASK-001",
        agent_role="reviewer",
        evidence_id="reviewer:TASK-001:round:1",
        parent_evidence_id="tester:TASK-002",
    ).to_dict()
    tester = agent_feedback_provenance(
        task_id="TASK-002",
        agent_role="tester",
        evidence_id="tester:TASK-002",
    ).to_dict()
    with pytest.raises(EvidenceGateError, match="task_id mismatch"):
        validate_reviewer_gate_evidence(reviewer, task_id="TASK-001", parents=(tester,))
