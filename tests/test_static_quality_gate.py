"""Static quality gate contracts (runtime level).

ruff is enforced with its conservative default rule set; mypy is opt-in and
recorded-only unless explicitly enforced; a missing tool is reported as
unavailable and never fails the gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from runtime.integration_verification import run_static_quality_gate


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_gate_passes_clean_deliverable_with_real_ruff(tmp_path: Path):
    _write(tmp_path / "todo.py", "MESSAGE = 'ok'\n\n\ndef show():\n    return MESSAGE\n")

    result = run_static_quality_gate(tmp_path)

    assert result["status"] == "passed"
    assert result["tools"]["ruff"]["status"] == "passed"
    assert result["tools"]["ruff"]["enforced"] is True


def test_gate_fails_on_undefined_name_and_is_enforced(tmp_path: Path):
    _write(tmp_path / "todo.py", "MESSAGE = 'ok'\n\nif False:\n    print(MISSING_NAME)\n")

    result = run_static_quality_gate(tmp_path)

    assert result["status"] == "failed"
    assert result["tools"]["ruff"]["status"] == "failed"
    assert "MISSING_NAME" in result["tools"]["ruff"]["output_tail"]


def test_gate_skips_without_python_files(tmp_path: Path):
    _write(tmp_path / "README.md", "docs only")

    result = run_static_quality_gate(tmp_path)

    assert result["status"] == "skipped"
    assert result["reason"] == "no python files"


def test_gate_skips_when_root_missing(tmp_path: Path):
    result = run_static_quality_gate(tmp_path / "missing")

    assert result["status"] == "skipped"
    assert "does not exist" in result["reason"]


def test_gate_reports_unavailable_tool_without_failing(tmp_path: Path):
    _write(tmp_path / "todo.py", "x = 1\n")

    result = run_static_quality_gate(tmp_path, tools=("leftpad_check",))

    assert result["status"] == "passed"
    assert result["tools"]["leftpad_check"]["status"] == "unavailable"


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_run_by_tool(results: dict[str, _FakeCompleted]):
    def fake_run(command, **kwargs: Any) -> _FakeCompleted:
        for name, outcome in results.items():
            if any(arg == name for arg in command):
                return outcome
        raise AssertionError(f"unexpected command: {command}")

    return fake_run


def test_mypy_is_recorded_only_by_default(tmp_path: Path, monkeypatch):
    _write(tmp_path / "todo.py", "x = 1\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run_by_tool({
            "ruff": _FakeCompleted(0),
            "mypy": _FakeCompleted(1, b"error: something is off\n"),
        }),
    )

    result = run_static_quality_gate(tmp_path, run_mypy=True)

    assert result["status"] == "passed"  # mypy finding recorded, not enforced
    assert result["tools"]["mypy"]["status"] == "failed"
    assert result["tools"]["mypy"]["enforced"] is False


def test_mypy_fails_the_gate_when_enforced(tmp_path: Path, monkeypatch):
    _write(tmp_path / "todo.py", "x = 1\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run_by_tool({
            "ruff": _FakeCompleted(0),
            "mypy": _FakeCompleted(1, b"error: something is off\n"),
        }),
    )

    result = run_static_quality_gate(tmp_path, run_mypy=True, enforce_mypy=True)

    assert result["status"] == "failed"
    assert result["tools"]["mypy"]["enforced"] is True
