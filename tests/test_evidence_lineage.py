from runtime.evidence_lineage import collect_lineage
from runtime.provenance import agent_feedback_provenance, agent_result_provenance, provenance_from_value, tool_evidence_provenance


def test_collect_lineage_follows_explicit_child_to_root_links() -> None:
    tool = tool_evidence_provenance(task_id="TASK-001", agent_role="developer", execution_id="tool:1").to_dict()
    tester = agent_feedback_provenance(task_id="TASK-001", agent_role="tester", evidence_id="tester:TASK-001", parent_evidence_id="tool:1").to_dict()
    reviewer = agent_feedback_provenance(task_id="TASK-001", agent_role="reviewer", evidence_id="reviewer:TASK-001:round:1", parent_evidence_id="tester:TASK-001").to_dict()

    chain = collect_lineage(reviewer, parents=(tester, tool))

    assert [item.evidence_id for item in chain] == ["reviewer:TASK-001:round:1", "tester:TASK-001", "tool:1"]


def test_collect_lineage_stops_when_parent_evidence_is_not_supplied() -> None:
    reviewer = agent_feedback_provenance(task_id="TASK-001", agent_role="reviewer", evidence_id="reviewer:TASK-001:round:1", parent_evidence_id="missing:evidence").to_dict()

    chain = collect_lineage(reviewer)

    assert [item.evidence_id for item in chain] == ["reviewer:TASK-001:round:1"]


def test_collect_lineage_rejects_cycles() -> None:
    first = agent_feedback_provenance(task_id="TASK-001", agent_role="tester", evidence_id="a", parent_evidence_id="b").to_dict()
    second = agent_feedback_provenance(task_id="TASK-001", agent_role="reviewer", evidence_id="b", parent_evidence_id="a").to_dict()

    try:
        collect_lineage(first, parents=(second,))
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("provenance cycles must be rejected")


def test_provenance_from_agent_result_synthesizes_stable_evidence_root() -> None:
    result = {
        "status": "completed",
        "agent": "developer",
        "task_id": "TASK-001",
        "message": "implemented",
        "data": {},
    }

    provenance = provenance_from_value(result)

    assert provenance == agent_result_provenance(task_id="TASK-001", agent_role="developer")
    assert provenance.source_type == "agent_result"
    assert provenance.evidence_id == "developer:TASK-001"


def test_explicit_result_provenance_takes_precedence_over_synthesized_root() -> None:
    explicit = agent_result_provenance(task_id="TASK-001", agent_role="developer", evidence_id="developer:explicit")
    result = {
        "status": "completed",
        "agent": "developer",
        "task_id": "TASK-001",
        "data": {"provenance": explicit.to_dict()},
    }

    assert provenance_from_value(result) == explicit
