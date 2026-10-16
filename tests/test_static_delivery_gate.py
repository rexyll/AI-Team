from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import subprocess

import pytest

import main
from core.project_result import ProjectResult
from runtime.release_anchor import create_release_anchor
from runtime.task import Task
from runtime.task_manager import TaskManager
import runtime.static_gate as gate_module

from core.project_orchestrator import ProjectOrchestrator
from runtime.static_gate import run_static_gate
from security.workspace import WorkspaceSandbox
from tests.test_delivery_pipeline import _router


def test_undefined_name_blocks_delivery_package(tmp_path: Path, monkeypatch):
    root = tmp_path / "product"
    root.mkdir()
    (root / "app.py").write_text("print(undefined_name)\n", encoding="utf-8")
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path),
        deliverable_dir="product",
        sandbox=WorkspaceSandbox(tmp_path),
        static_gate=run_static_gate,
    )
    plan = orchestrator.create_plan("统计文本词频")
    manager = orchestrator.build_task_manager(plan)

    def unexpected_package(*args, **kwargs):
        raise AssertionError("A failed gate must not build a release package")

    monkeypatch.setattr("core.project_orchestrator.create_deployment_bundle", unexpected_package)
    delivery = orchestrator._run_delivery_phase(manager, project="wordcount")

    assert delivery["static_gate"]["status"] == "failed"
    lint = next(check for check in delivery["static_gate"]["checks"] if check["name"] == "ruff")
    assert lint["status"] == "failed"
    assert "F821" in lint["output"]
    assert delivery["release_ready"] is False
    assert "package" not in delivery
    assert (root / "docs" / "static_gate.json").is_file()


def test_clean_source_passes_without_importing_it(tmp_path):
    (tmp_path / "app.py").write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    assert run_static_gate(tmp_path)["status"] == "passed"


def test_type_error_fails(tmp_path):
    (tmp_path / "app.py").write_text("value: int = 'wrong'\n", encoding="utf-8")
    result = run_static_gate(tmp_path)
    assert result["status"] == "failed"
    assert next(c for c in result["checks"] if c["name"] == "mypy")["status"] == "failed"


@pytest.mark.parametrize("manifest", ["requirements.txt", "pyproject.toml"])
def test_dependency_manifests_produce_an_audit_check(tmp_path, manifest):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / manifest).write_text("", encoding="utf-8")
    result = run_static_gate(tmp_path)
    audit = next(c for c in result["checks"] if c["name"] == "dependency_audit")
    # The audit check must exist and be a real verdict — never silently absent.
    assert audit["status"] in {"passed", "failed", "unavailable", "timeout", "not_applicable"}
    if manifest == "pyproject.toml":
        # Only requirements.txt feeds pip-audit today; pyproject still gets a check.
        assert audit["status"] in {"passed", "not_applicable", "unavailable"}


def test_missing_pip_audit_is_unavailable_not_passed(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("flask==0.12.2\n", encoding="utf-8")
    monkeypatch.setattr(gate_module.importlib.util, "find_spec", lambda name: None)
    result = run_static_gate(tmp_path)
    assert result["status"] == "unverified"
    audit = next(c for c in result["checks"] if c["name"] == "dependency_audit")
    assert audit["status"] == "unavailable"


def test_known_vulnerable_pin_fails_the_gate(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("flask==0.12.2\n", encoding="utf-8")
    result = run_static_gate(tmp_path)
    assert result["status"] == "failed"
    audit = next(c for c in result["checks"] if c["name"] == "dependency_audit")
    assert audit["status"] == "failed"
    assert "vulnerabilities" in audit["output"]


def test_missing_tools_and_empty_project_are_unverified(tmp_path, monkeypatch):
    assert run_static_gate(tmp_path)["status"] == "unverified"
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(gate_module.importlib.util, "find_spec", lambda name: None)
    result = run_static_gate(tmp_path)
    assert result["status"] == "unverified"
    assert result["checks"][0]["status"] == "unavailable"


def test_timeout_is_not_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_module.importlib.util, "find_spec", lambda name: object())
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)
    monkeypatch.setattr(gate_module.subprocess, "run", timeout)
    assert gate_module._run("ruff", [], tmp_path, 1)["status"] == "timeout"


def test_unverified_gate_changes_project_result_and_roundtrips(tmp_path, monkeypatch):
    manager = TaskManager([Task(id="T1", title="t", description="d", role="developer", status="completed")])
    orchestrator = ProjectOrchestrator(_router(tmp_path), orchestrator_factory=lambda *args: SimpleNamespace(run=lambda: None))
    monkeypatch.setattr(orchestrator, "_run_delivery_phase", lambda *args, **kwargs: {"static_gate": {"status": "unverified"}})
    result = orchestrator.execute(manager)
    assert not result.success
    assert result.status == "failed"
    assert result.completed_tasks == 1
    assert ProjectResult.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("mode", ["text", "json"])
@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("verdict,code", [("passed", 0), ("failed", 1), ("unverified", 1), (None, 1)])
def test_cli_static_gate_exit_code(monkeypatch, mode, interactive, verdict, code):
    manager = TaskManager([Task(id="T1", title="t", description="d", role="developer", status="completed")])
    result = replace(ProjectResult.from_task_manager(manager), static_gate_verdict=verdict)
    captured = {}
    def run(*args, **kwargs):
        captured.update(kwargs)
        return (manager, result, None) if interactive else (manager, result, None)
    monkeypatch.setattr(main, "run_interactive_session" if interactive else "run_project", run)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "demo", "--static-gate", "--output", mode] + (["--interactive"] if interactive else []))
    assert main.main() == code
    assert captured["static_gate"] is True


def test_acceptance_and_static_gate_verdicts_coexist(tmp_path, monkeypatch):
    root = tmp_path / "product"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path),
        deliverable_dir="product",
        sandbox=WorkspaceSandbox(tmp_path),
        static_gate=run_static_gate,
    )
    orchestrator.create_plan("统计文本词频")
    manager = orchestrator.build_task_manager(orchestrator.last_plan)
    for status in ("ready", "running"):
        getattr(manager, f"mark_{status}")("TASK-001")
    manager.record_result("TASK-001", {"message": "ok", "data": {"tests": []}})
    manager.mark_completed("TASK-001")

    result = orchestrator.execute(manager)

    assert result.acceptance_verdict == "passed"
    assert result.static_gate_verdict == "passed"
    assert result.success
    assert orchestrator.last_delivery["release_ready"] is True


def test_release_anchor_tags_delivery_when_gate_and_acceptance_pass(tmp_path):
    import subprocess

    root = tmp_path / "product"
    root.mkdir()
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.invalid"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True)
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path),
        deliverable_dir="product",
        sandbox=WorkspaceSandbox(tmp_path),
        static_gate=run_static_gate,
        release_anchor=create_release_anchor,
    )
    orchestrator.create_plan("统计文本词频")
    manager = orchestrator.build_task_manager(orchestrator.last_plan)
    for status in ("ready", "running"):
        getattr(manager, f"mark_{status}")("TASK-001")
    manager.record_result("TASK-001", {"message": "ok", "data": {"tests": []}})
    manager.mark_completed("TASK-001")

    orchestrator.execute(manager)

    anchor = orchestrator.last_delivery["release_anchor"]
    assert anchor["tag"] == "release/wordcount-1.0.0"
    assert anchor["commit"]
    assert anchor["reused"] is False


def test_release_anchor_skipped_when_gate_fails(tmp_path, monkeypatch):
    root = tmp_path / "product"
    root.mkdir()
    (root / "app.py").write_text("print(undefined_name)\n", encoding="utf-8")
    orchestrator = ProjectOrchestrator(
        agent_router=_router(tmp_path),
        deliverable_dir="product",
        sandbox=WorkspaceSandbox(tmp_path),
        static_gate=run_static_gate,
        release_anchor=create_release_anchor,
    )
    orchestrator.create_plan("统计文本词频")
    manager = orchestrator.build_task_manager(orchestrator.last_plan)

    orchestrator.execute(manager)

    assert "release_anchor" not in orchestrator.last_delivery
