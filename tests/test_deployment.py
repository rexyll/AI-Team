from __future__ import annotations

import zipfile
from pathlib import Path

from runtime.deployment import (
    create_deployment_bundle,
    find_test_files,
    generate_dockerfile_template,
    generate_installer_scripts,
    run_smoke_verification,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_find_test_files_follows_pytest_convention(tmp_path: Path):
    _write(tmp_path / "todo.py", "x = 1")
    _write(tmp_path / "test_todo.py", "def test_a(): pass")
    _write(tmp_path / "smoke_test.py", "def test_b(): pass")
    _write(tmp_path / "__pycache__" / "test_junk.py", "pass")

    tests = find_test_files(tmp_path)

    assert tests == ["smoke_test.py", "test_todo.py"]


def test_installer_scripts_carry_project_and_smoke_command():
    scripts = generate_installer_scripts(project="Todo CLI", test_files=["test_todo.py"])

    assert "Todo CLI" in scripts["install.ps1"]
    assert "python -m pytest test_todo.py" in scripts["install.sh"]
    assert "requirements.txt" in scripts["install.ps1"]


def test_dockerfile_template_documents_placeholder():
    dockerfile = generate_dockerfile_template(project="Todo CLI")

    assert "python:3.12-slim" in dockerfile
    assert "按部署指引修改" in dockerfile


def test_smoke_verification_runs_tests_in_fresh_copy(tmp_path: Path):
    _write(tmp_path / "todo.py", "MESSAGE = 'deployed'")
    _write(tmp_path / "test_todo.py", "import todo\n\ndef test_message():\n    assert todo.MESSAGE == 'deployed'\n")

    result = run_smoke_verification(tmp_path, timeout=120)

    assert result["status"] == "passed"
    assert result["exit_code"] == 0


def test_smoke_skips_without_tests(tmp_path: Path):
    _write(tmp_path / "app.py", "x = 1")

    result = run_smoke_verification(tmp_path)

    assert result["status"] == "skipped"


def test_deployment_bundle_contains_installers_and_smoke(tmp_path: Path):
    root = tmp_path / "e2e_delivery"
    _write(root / "todo.py", "MESSAGE = 'ok'")
    _write(root / "test_todo.py", "import todo\n\ndef test_ok():\n    assert todo.MESSAGE == 'ok'\n")

    bundle = create_deployment_bundle(root, project="todo", smoke_timeout=120)

    assert bundle["smoke"]["status"] == "passed"
    archive = Path(bundle["bundle"])
    with zipfile.ZipFile(archive) as bundle_zip:
        members = set(bundle_zip.namelist())
    assert {"install.ps1", "install.sh", "Dockerfile", "SMOKE_REPORT.md"} <= members
    assert "todo.py" in members
    assert bundle["checksum"]


def test_deployment_bundle_smoke_failure_is_reported(tmp_path: Path):
    root = tmp_path / "e2e_delivery"
    _write(root / "todo.py", "MESSAGE = 'broken'")
    _write(root / "test_todo.py", "import todo\n\ndef test_ok():\n    assert todo.MESSAGE == 'ok'\n")

    bundle = create_deployment_bundle(root, smoke_timeout=120)

    assert bundle["smoke"]["status"] == "failed"
    report = Path(bundle["bundle"]).parent
    with zipfile.ZipFile(bundle["bundle"]) as bundle_zip:
        smoke_report = bundle_zip.read("SMOKE_REPORT.md").decode("utf-8")
    assert "FAILED" in smoke_report
    assert report.is_dir()
