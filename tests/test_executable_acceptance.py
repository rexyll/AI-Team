from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runtime.acceptance import RequirementEntry
from runtime.executable_acceptance import (
    evaluate_executable_acceptance,
    load_acceptance_test_specs,
    render_executable_acceptance_report,
    write_executable_acceptance_report,
)


def _entry(req_id: str = "REQ-001", priority: str = "必须") -> RequirementEntry:
    return RequirementEntry(req_id, priority, True, "核心功能")


def _integration(*, status: str = "passed", started_at: str | None = None, cases=None):
    return {
        "status": status,
        "command": "python -m pytest tests/test_app.py -q",
        "exit_code": 0 if status == "passed" else 1,
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "test_cases": cases if cases is not None else [
            {
                "selector": "tests.test_app::test_accepts_input",
                "status": "passed",
                "duration_seconds": 0.01,
                "summary": None,
            }
        ],
    }


def _spec():
    return [{
        "test_id": "AT-001",
        "requirement_id": "REQ-001",
        "selector": "tests.test_app::test_accepts_input",
    }]


def test_loads_strict_acceptance_spec(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "acceptance_tests.json").write_text(json.dumps({
        "schema_version": 1,
        "tests": _spec(),
    }), encoding="utf-8")

    assert load_acceptance_test_specs(docs) == _spec()


@pytest.mark.parametrize("payload", [
    [],
    {"schema_version": 2, "tests": []},
    {"schema_version": 1, "tests": "not-a-list"},
    {"schema_version": 1, "tests": [{"test_id": "AT-001", "requirement_id": "REQ-001"}]},
    {"schema_version": 1, "tests": [{"test_id": "AT-001", "requirement_id": "REQ-001", "selector": "../escape::test"}]},
])
def test_rejects_malformed_or_unsafe_acceptance_spec(tmp_path: Path, payload):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "acceptance_tests.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_acceptance_test_specs(docs)


def test_missing_spec_is_empty(tmp_path: Path):
    assert load_acceptance_test_specs(tmp_path / "docs") == []


def test_pass_requires_linked_test_that_was_executed_and_passed():
    result = evaluate_executable_acceptance([_entry()], _spec(), _integration())

    assert result["verdict"] == "passed"
    assert result["gaps"] == []
    assert result["requirements"][0]["tests"][0]["status"] == "passed"


def test_mandatory_requirement_without_test_is_failed():
    result = evaluate_executable_acceptance([_entry()], [], _integration())

    assert result["verdict"] == "failed"
    assert "REQ-001 has no executable acceptance test" in result["gaps"]


def test_missing_execution_is_not_executed():
    result = evaluate_executable_acceptance(
        [_entry()],
        _spec(),
        _integration(cases=[]),
    )

    assert result["verdict"] == "failed"
    assert any("AT-001 not_executed" in gap for gap in result["gaps"])


def test_failed_test_is_failed_even_when_suite_claims_passed():
    result = evaluate_executable_acceptance(
        [_entry()],
        _spec(),
        _integration(cases=[{
            "selector": "tests.test_app::test_accepts_input",
            "status": "failed",
        }]),
    )

    assert result["verdict"] == "failed"
    assert any("AT-001 failed" in gap for gap in result["gaps"])


def test_skipped_suite_is_not_executed():
    result = evaluate_executable_acceptance(
        [_entry()],
        _spec(),
        _integration(status="skipped", cases=[]),
    )

    assert result["verdict"] == "not_executed"


def test_stale_evidence_is_not_executed():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=25)).isoformat()
    result = evaluate_executable_acceptance(
        [_entry()],
        _spec(),
        _integration(started_at=old),
        now=now,
    )

    assert result["verdict"] == "not_executed"
    assert any("missing or stale" in gap for gap in result["gaps"])


def test_optional_requirement_gap_is_warning_not_release_blocker():
    result = evaluate_executable_acceptance(
        [_entry(priority="可选")],
        [],
        _integration(),
    )

    assert result["verdict"] == "passed"
    assert result["gaps"] == []
    assert result["warnings"] == ["REQ-001 has no executable acceptance test"]


def test_report_write_is_atomic_and_contains_execution_lineage(tmp_path: Path):
    result = evaluate_executable_acceptance([_entry()], _spec(), _integration())
    report = render_executable_acceptance_report(result, project="fixture")
    assert "AT-001" in report
    assert "tests.test_app::test_accepts_input" in report
    assert "PASSED" in report

    path = write_executable_acceptance_report(tmp_path / "docs", result, project="fixture")
    assert path.name == "executable_acceptance_report.md"
    assert path.read_text(encoding="utf-8") == report
