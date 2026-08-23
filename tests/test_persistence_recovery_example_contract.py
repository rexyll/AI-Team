from pathlib import Path

from examples.persistence_recovery import PROJECT_ID, run_example


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_README = ROOT / "examples" / "README.md"


def test_recovery_restores_semantically_equivalent_project(tmp_path) -> None:
    result = run_example(tmp_path / "demo")

    assert result["project_id"] == PROJECT_ID
    assert result["recovery"]["equivalent"] is True
    assert result["recovered_task_statuses"] == {
        "TASK-R001": "completed",
        "TASK-R002": "completed",
    }


def test_recovered_event_stream_supports_cross_store_query(tmp_path) -> None:
    result = run_example(tmp_path / "demo")

    assert result["lifecycle"] == "completed"
    assert result["second_task_review_status"] == "approved"
    assert result["last_event"][0] == "EVENT-R010"
    assert result["last_event"][1] == "reviewer_approved"


def test_recovered_history_supports_read_only_audit(tmp_path) -> None:
    result = run_example(tmp_path / "demo")

    summary = result["audit_summary"]
    assert summary["total"] == 2
    assert summary["by_status"] == {"completed": 2}
    assert summary["by_agent_role"] == {"developer": 2}
    assert result["developer_record_count"] == 2
    assert result["audit_consistency"]["consistent"] is True


def test_example_documents_restart_and_read_only_boundaries() -> None:
    content = EXAMPLES_README.read_text(encoding="utf-8")

    assert "## Persistence and Recovery Walkthrough" in content
    assert "restart" in content
    assert "read-only" in content
