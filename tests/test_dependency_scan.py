"""Deliverable dependency declaration audit contracts."""

from __future__ import annotations

from pathlib import Path

from runtime.dependency_scan import scan_deliverable_dependencies


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_parses_pins_and_detects_undeclared_imports(tmp_path: Path):
    _write(
        tmp_path / "requirements.txt",
        "requests==2.0.0\n"
        "numpy>=1.0\n"
        "# a comment line\n"
        "-r extras.txt\n"
        "colorama; python_version > '3'\n",
    )
    _write(tmp_path / "todo.py", "import json\nimport requests\nimport numpy\nimport colorama\nimport flask\nimport todo_helpers\n")
    _write(tmp_path / "todo_helpers.py", "x = 1\n")

    result = scan_deliverable_dependencies(tmp_path)

    assert result["status"] == "completed"
    assert result["requirements_file"] is True
    assert result["declared"] == ["requests==2.0.0", "numpy>=1.0", "colorama"]
    # numpy carries a range and colorama has no specifier at all: both unpinned.
    assert result["unpinned"] == ["numpy", "colorama"]
    # flask is imported but never declared; json/todo_helpers are stdlib/local.
    assert result["undeclared_imports"] == ["flask"]
    assert result["vulnerability_lookup"]["status"] == "unavailable"


def test_scan_without_requirements_reports_empty_sbom(tmp_path: Path):
    _write(tmp_path / "todo.py", "import json\n")

    result = scan_deliverable_dependencies(tmp_path)

    assert result["status"] == "completed"
    assert result["requirements_file"] is False
    assert result["declared"] == []
    assert result["undeclared_imports"] == []


def test_scan_skips_when_root_missing(tmp_path: Path):
    result = scan_deliverable_dependencies(tmp_path / "missing")

    assert result["status"] == "skipped"
    assert "does not exist" in result["reason"]


def test_scan_ignores_unparsable_source_files(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "requests==2.0.0\n")
    _write(tmp_path / "todo.py", "def broken(:\n")

    result = scan_deliverable_dependencies(tmp_path)

    assert result["status"] == "completed"
    assert result["unpinned"] == []
    assert result["undeclared_imports"] == []
