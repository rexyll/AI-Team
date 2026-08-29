import pytest

from runtime.provenance import EvidenceProvenance, agent_feedback_provenance, tool_evidence_provenance
from security.runtime_capability import DEFAULT_RUNTIME_CAPABILITY_POLICY
from security.tool_permission import ToolPermissionError


def test_runtime_capability_policy_is_deny_by_default_for_unknown_roles() -> None:
    policy = DEFAULT_RUNTIME_CAPABILITY_POLICY

    assert policy.allows("developer", "read_file")
    assert policy.allows("developer", "write_file")
    assert policy.allows("developer", "run_command")
    assert not policy.allows("reviewer", "write_file")
    assert not policy.allows("unknown", "read_file")


def test_runtime_capability_policy_filters_tools_exposed_to_agent() -> None:
    policy = DEFAULT_RUNTIME_CAPABILITY_POLICY

    assert policy.filter_tool_names("reviewer", ["read_file", "write_file", "run_command"]) == ["read_file"]
    assert policy.filter_tool_names("developer", ["read_file", "write_file", "run_command"]) == ["read_file", "write_file", "run_command"]


def test_runtime_capability_policy_rejects_unauthorized_execution() -> None:
    with pytest.raises(ToolPermissionError):
        DEFAULT_RUNTIME_CAPABILITY_POLICY.require("reviewer", "write_file")


def test_evidence_provenance_round_trips_to_dict() -> None:
    provenance = EvidenceProvenance(
        source_role="developer",
        source_type="tool_execution",
        task_id="TASK-001",
        evidence_id="call-1",
    )

    assert provenance.to_dict() == {
        "source_role": "developer",
        "source_type": "tool_execution",
        "task_id": "TASK-001",
        "evidence_id": "call-1",
        "status": "observed",
        "parent_evidence_id": None,
    }


def test_tool_and_agent_feedback_provenance_have_distinct_source_types() -> None:
    tool = tool_evidence_provenance(task_id="TASK-001", agent_role="developer", execution_id="call-1")
    feedback = agent_feedback_provenance(task_id="TASK-001", agent_role="tester", evidence_id="tester:TASK-001")

    assert tool.source_type == "tool_execution"
    assert feedback.source_type == "agent_feedback"
    assert tool.evidence_id == "call-1"
    assert feedback.evidence_id == "tester:TASK-001"
