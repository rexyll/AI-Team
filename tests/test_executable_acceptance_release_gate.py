from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from core.project_orchestrator import ProjectOrchestrator
from runtime.release_gate import evaluate_release_gate


def test_release_gate_blocks_failed_executable_acceptance():
    result = evaluate_release_gate(
        integration={"status": "passed"},
        acceptance={"verdict": "failed", "gaps": ["REQ-001 has no executable acceptance test"]},
    )

    assert result["status"] == "blocked"
    assert result["blockers"] == [{
        "code": "acceptance_failed",
        "reason": "可执行需求验收证据未通过或未执行",
    }]


def test_release_gate_blocks_not_executed_acceptance():
    result = evaluate_release_gate(
        acceptance={"verdict": "not_executed", "gaps": ["AT-001 not_executed"]},
    )

    assert result["status"] == "blocked"
    assert result["blockers"][0]["code"] == "acceptance_failed"


def test_release_gate_allows_passing_executable_acceptance():
    result = evaluate_release_gate(
        integration={"status": "passed"},
        acceptance={"verdict": "passed", "gaps": []},
    )

    assert result == {"status": "allowed", "blockers": []}


def test_release_gate_keeps_acceptance_optional_for_legacy_projects():
    result = evaluate_release_gate(integration={"status": "passed"})

    assert result == {"status": "allowed", "blockers": []}


_ANALYSIS = """# Requirements

## Functional requirements

### REQ-001 Core behavior (必须)
验收标准：valid input produces the expected output.
"""


def _project(tmp_path: Path) -> ProjectOrchestrator:
    project = ProjectOrchestrator(agent_router=object())
    project.last_requirement_analysis = _ANALYSIS
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "requirements.md").write_text("REQ-001", encoding="utf-8")
    (docs / "test_report.md").write_text("REQ-001 executed", encoding="utf-8")
    return project


def test_project_acceptance_phase_uses_actual_junit_execution(tmp_path: Path):
    project = _project(tmp_path)
    (tmp_path / "docs" / "acceptance_tests.json").write_text(json.dumps({
        "schema_version": 1,
        "tests": [{
            "test_id": "AT-001",
            "requirement_id": "REQ-001",
            "selector": "tests.test_app::test_core",
        }],
    }), encoding="utf-8")
    integration = {
        "status": "passed",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "test_cases": [{
            "selector": "tests.test_app::test_core",
            "status": "passed",
            "duration_seconds": 0.01,
        }],
    }

    result = project._run_acceptance_phase(tmp_path, project="fixture", integration=integration)

    assert result["verdict"] == "passed"
    assert result["traceability_verdict"] == "passed"
    assert result["executable_verdict"] == "passed"
    assert Path(result["executable_report"]).is_file()


def test_project_acceptance_phase_fails_closed_when_test_mapping_missing(tmp_path: Path):
    project = _project(tmp_path)
    integration = {
        "status": "passed",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "test_cases": [],
    }

    result = project._run_acceptance_phase(tmp_path, project="fixture", integration=integration)

    assert result["verdict"] == "failed"
    assert any("no executable acceptance test" in gap for gap in result["gaps"])


def test_project_acceptance_phase_fails_closed_when_suite_was_skipped(tmp_path: Path):
    project = _project(tmp_path)
    (tmp_path / "docs" / "acceptance_tests.json").write_text(json.dumps({
        "schema_version": 1,
        "tests": [{
            "test_id": "AT-001",
            "requirement_id": "REQ-001",
            "selector": "tests.test_app::test_core",
        }],
    }), encoding="utf-8")

    result = project._run_acceptance_phase(
        tmp_path,
        project="fixture",
        integration={"status": "skipped", "test_cases": []},
    )

    assert result["verdict"] == "not_executed"
