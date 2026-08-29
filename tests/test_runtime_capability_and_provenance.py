import pytest

from agents.reviewer import ReviewerAgent
from agents import tester as tester_module
from runtime.agent_context import AgentContext
from runtime.provenance import EvidenceProvenance, agent_feedback_provenance, tool_evidence_provenance
from runtime.tool_execution_record import ToolExecutionRecord
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


def test_tool_execution_record_contains_immutable_provenance_metadata() -> None:
    record = ToolExecutionRecord(
        execution_id="call-1",
        task_id="TASK-001",
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-29T00:00:00+00:00",
        completed_at="2026-08-29T00:00:01+00:00",
        status="completed",
        output="ok",
    )

    assert record.metadata["provenance"] == {
        "source_role": "developer",
        "source_type": "tool_execution",
        "task_id": "TASK-001",
        "evidence_id": "call-1",
        "status": "observed",
        "parent_evidence_id": None,
    }


def test_tool_execution_context_projection_excludes_internal_provenance() -> None:
    record = ToolExecutionRecord(
        execution_id="call-1",
        task_id="TASK-001",
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-29T00:00:00+00:00",
        completed_at="2026-08-29T00:00:01+00:00",
        status="completed",
        output="ok",
        metadata={"iteration": 1},
    )

    assert record.to_context_dict() == {
        "execution_id": "call-1",
        "task_id": "TASK-001",
        "agent_role": "developer",
        "tool_name": "read_file",
        "started_at": "2026-08-29T00:00:00+00:00",
        "completed_at": "2026-08-29T00:00:01+00:00",
        "status": "completed",
        "arguments": {},
        "output": "ok",
        "error": None,
        "metadata": {"iteration": 1},
    }


def test_tester_feedback_exposes_provenance() -> None:
    context = AgentContext(
        task_id="TASK-TEST",
        task_title="test",
        task_description="verify",
        role="tester",
        status="running",
    )

    data = tester_module.TesterAgent._build_result_data(content="TEST_FAILED\nreason", decision="failed", context=context)

    assert data["provenance"]["source_role"] == "tester"
    assert data["provenance"]["source_type"] == "agent_feedback"
    assert data["provenance"]["task_id"] == "TASK-TEST"


def test_reviewer_feedback_exposes_provenance_and_round() -> None:
    context = AgentContext(
        task_id="TASK-REVIEW",
        task_title="review",
        task_description="verify",
        role="reviewer",
        status="running",
        review_round=3,
    )

    data = ReviewerAgent._build_result_data(content="APPROVED\nreason", decision="approved", context=context)

    assert data["provenance"]["source_role"] == "reviewer"
    assert data["provenance"]["source_type"] == "agent_feedback"
    assert data["provenance"]["evidence_id"] == "reviewer:TASK-REVIEW:round:3"
