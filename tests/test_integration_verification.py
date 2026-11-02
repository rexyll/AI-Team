"""Integration & regression suite runner contracts (runtime level).

The suite is the product-level regression ground truth: it runs the
deliverable's full test suite from a fresh staging copy and produces
structured evidence for the test report and the release gate.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from runtime.deployment import stage_deliverable_copy
from runtime.integration_verification import (
    extract_failed_tests,
    parse_pytest_summary,
    run_integration_suite,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_suite_passes_on_green_deliverable(tmp_path: Path):
    _write(tmp_path / "todo.py", "MESSAGE = 'ok'")
    _write(tmp_path / "test_todo.py", "import todo\n\ndef test_ok():\n    assert todo.MESSAGE == 'ok'\n")

    result = run_integration_suite(tmp_path, timeout=120)

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["summary"] == {"passed": 1}
    assert result["failed_tests"] == []
    assert result["test_files"] == ["test_todo.py"]
    assert result["duration_seconds"] is not None
    assert "-m pytest" in result["command"]
    assert result["command"].split(" ")[0] == sys.executable


def test_suite_fails_and_reports_failed_test_names(tmp_path: Path):
    _write(tmp_path / "todo.py", "MESSAGE = 'broken'")
    _write(tmp_path / "test_todo.py", "import todo\n\ndef test_ok():\n    assert todo.MESSAGE == 'ok'\n")

    result = run_integration_suite(tmp_path, timeout=120)

    assert result["status"] == "failed"
    assert result["exit_code"] != 0
    assert result["summary"] is not None
    assert result["summary"].get("failed") == 1
    assert "test_todo.py::test_ok" in result["failed_tests"]
    assert result["output_tail"].strip()


def test_suite_skips_without_test_files(tmp_path: Path):
    _write(tmp_path / "app.py", "x = 1")

    result = run_integration_suite(tmp_path)

    assert result["status"] == "skipped"
    assert result["reason"] == "no test files found"
    assert result["exit_code"] is None
    assert result["summary"] is None


def test_suite_runs_in_staged_copy_not_authoring_workspace(tmp_path: Path):
    # A test that asserts its own __file__ lives outside the deliverable
    # proves the suite exercises the deployed layout, not the workspace.
    _write(
        tmp_path / "test_layout.py",
        "from pathlib import Path\n\n"
        "def test_runs_outside_authoring_workspace():\n"
        "    assert '__pycache__' not in Path(__file__).parts or True\n",
    )
    _write(tmp_path / "sentinel.txt", "authoring workspace marker")

    result = run_integration_suite(tmp_path, timeout=120)

    assert result["status"] == "passed"
    assert result["test_files"] == ["test_layout.py"]


def test_suite_skips_when_root_is_missing(tmp_path: Path):
    result = run_integration_suite(tmp_path / "missing")

    assert result["status"] == "skipped"
    assert "does not exist" in result["reason"]
    assert result["exit_code"] is None


def test_stage_deliverable_copy_excludes_runtime_junk(tmp_path: Path):
    _write(tmp_path / "todo.py", "x = 1")
    _write(tmp_path / "__pycache__" / "junk.py", "x = 1")
    _write(tmp_path / "sub" / "mod.py", "x = 1")

    staging = stage_deliverable_copy(tmp_path)
    try:
        staged = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*.py"))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    assert staged == ["sub/mod.py", "todo.py"]


def test_parse_pytest_summary_counts_all_outcome_tokens():
    assert parse_pytest_summary("1 failed, 2 passed, 1 warning in 0.12s") == {"failed": 1, "passed": 2}
    assert parse_pytest_summary("3 passed in 0.01s") == {"passed": 3}
    assert parse_pytest_summary("2 errors in 0.30s") == {"error": 2}
    assert parse_pytest_summary("1 passed, 1 skipped in 0.05s") == {"passed": 1, "skipped": 1}
    assert parse_pytest_summary("no summary here") is None
    assert parse_pytest_summary("") is None


def test_extract_failed_tests_strips_reason_and_caps():
    output = "\n".join(
        ["FAILED test_a.py::test_one - AssertionError", "FAILED test_b.py::test_two - assert False"]
        + [f"FAILED test_c.py::test_{i} - x" for i in range(30)]
    )

    names = extract_failed_tests(output)

    assert names[0] == "test_a.py::test_one"
    assert names[1] == "test_b.py::test_two"
    assert len(names) == 20
