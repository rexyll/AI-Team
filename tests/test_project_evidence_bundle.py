from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.delivery_manifest import write_delivery_manifest
from runtime.project_evidence_bundle import (
    build_project_evidence_bundle,
    validate_project_evidence_bundle,
    write_project_evidence_bundle,
)


def _project(tmp_path: Path):
    root = tmp_path / "deliverable"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('safe')\n", encoding="utf-8")
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"not shipped")
    manifest = write_delivery_manifest(root, project="fixture")

    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("src/app.py", "print('safe')\n")
    package_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

    task = SimpleNamespace(
        id="TASK-001",
        role="developer",
        status="completed",
        dependencies=[],
        title="Implement the CLI",
        description="A fixture description that must not be copied verbatim.",
        context={
            "workspace_lease": {
                "lease_id": "lease-0123456789abcdef",
                "task_id": "TASK-001",
                "disposition": "merged",
            },
            "workspace_merge": {
                "changed": [],
                "added": ["src/app.py"],
                "deleted": [],
            },
            "tool_execution_history": [],
        },
    )
    tool = {
        "execution_id": "exec-adapter-001",
        "task_id": "PROJECT-ADAPTER-fixture",
        "agent_role": "developer",
        "tool_name": "run_command",
        "started_at": "2026-11-15T10:00:00+00:00",
        "completed_at": "2026-11-15T10:00:02+00:00",
        "status": "completed",
        "arguments": {"command": "python -m pytest", "env": {"TOKEN": "do-not-export"}},
    }
    delivery = {
        "manifest": str(manifest),
        "package": {"archive": str(archive), "checksum": package_sha},
        "integration": {
            "status": "passed",
            "rounds": 0,
            "suite": {
                "status": "passed",
                "exit_code": 0,
                "summary": {"passed": 2},
                "duration_seconds": 0.2,
                "test_cases": [{
                    "selector": "tests.test_app::test_ok",
                    "status": "passed",
                    "duration_seconds": 0.01,
                    "summary": "not exported",
                }],
            },
            "adapter": {
                "status": "passed",
                "adapter": "python",
                "language": "python",
                "signals": ["pyproject.toml"],
                "actions": {
                    "install": {"status": "passed", "exit_code": 0},
                    "build": {"status": "passed", "exit_code": 0},
                    "test": {"status": "passed", "exit_code": 0},
                    "smoke": {"status": "passed", "exit_code": 0},
                    "package": {"status": "passed", "exit_code": 0},
                },
                "tool_execution_history": [tool],
            },
        },
        "qa": {"status": "completed", "verdict": "QA_PASSED"},
        "security": {"status": "completed", "verdict": "SEC_PASSED", "findings": []},
        "acceptance": {"verdict": "passed", "gaps": [], "warnings": [], "test_count": 1},
        "release": {"status": "not_requested"},
        "smoke": {"status": "passed"},
    }
    project = SimpleNamespace(
        _project_id="T21-8-EVIDENCE-FIXTURE",
        last_plan={
            "project": "evidence-fixture",
            "tasks": [{
                "id": "TASK-001",
                "role": "developer",
                "title": "Implement the CLI",
                "description": "fixture",
                "dependencies": [],
            }],
        },
        last_task_manager=SimpleNamespace(get_all_tasks=lambda: [task]),
        last_project_profile=SimpleNamespace(to_dict=lambda: {
            "project_type": "cli",
            "ui_required": False,
            "specialists": ["cli"],
            "signals": ["cli"],
        }),
        last_requirement_analysis=(
            "## 必须需求\n"
            "- REQ-001 CLI accepts an integer input\n"
            "  - 验收：valid integer returns a result\n"
        ),
        last_delivery=delivery,
        last_result=SimpleNamespace(status="completed", success=True),
        last_scm_observation=None,
    )
    return project, root, archive


def test_builds_privacy_minimized_bundle_with_real_artifact_hashes(tmp_path: Path):
    project, root, archive = _project(tmp_path)
    requirement = "Build a private sample CLI; PRIVATE-INPUT-SENTINEL"

    bundle = build_project_evidence_bundle(
        project,
        requirement=requirement,
        deliverable_root=root,
        evidence_level="deterministic_orchestration",
        role_execution={"planner": "scripted_test_double", "doc_writer": "mock_llm"},
        limitations=["Analyst and QA reasoning are not part of this fixture."],
    )

    validate_project_evidence_bundle(bundle)
    assert bundle["project"]["id"] == "T21-8-EVIDENCE-FIXTURE"
    assert bundle["requirement"]["ids"][0]["id"] == "REQ-001"
    assert bundle["task_graph"]["workspace_isolation"]["status"] == "passed"
    task = bundle["task_graph"]["tasks"][0]
    assert task["workspace"]["lease_id"] == "lease-0123456789abcdef"
    assert task["workspace"]["disposition"] == "merged"
    assert bundle["tool_invocations"][0]["tool"] == "run_command"
    assert bundle["tool_invocations"][0]["duration_seconds"] == 2.0
    assert "arguments" not in bundle["tool_invocations"][0]
    assert bundle["artifacts"]["package"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert bundle["artifacts"]["package"]["recorded_sha256_matches"] is True
    assert ".venv/Scripts/python.exe" not in {
        item["path"] for item in bundle["artifacts"]["manifest"]["members"]
    }
    encoded = json.dumps(bundle, ensure_ascii=False)
    assert "PRIVATE-INPUT-SENTINEL" not in encoded
    assert "do-not-export" not in encoded
    assert "fixture description that must not be copied verbatim" not in encoded
    assert bundle["privacy"]["raw_requirement_included"] is False


def test_writer_persists_canonical_bundle_and_digest(tmp_path: Path):
    project, root, _ = _project(tmp_path)
    output = tmp_path / "ci-artifacts" / "evidence.json"

    result = write_project_evidence_bundle(
        project,
        requirement="Build the fixture CLI",
        deliverable_root=root,
        output_path=output,
        evidence_level="deterministic_orchestration",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    validate_project_evidence_bundle(payload)
    assert result["filename"] == "evidence.json"
    assert result["sha256"] == payload["evidence_sha256"]
    assert result["bytes"] == output.stat().st_size


def test_rejects_digest_tampering(tmp_path: Path):
    project, root, _ = _project(tmp_path)
    bundle = build_project_evidence_bundle(
        project,
        requirement="Build the fixture CLI",
        deliverable_root=root,
        evidence_level="deterministic_orchestration",
    )
    bundle["task_graph"]["tasks"][0]["status"] = "failed"

    with pytest.raises(ValueError, match="digest mismatch"):
        validate_project_evidence_bundle(bundle)


def test_rejects_workspace_lease_without_identity_or_terminal_disposition(tmp_path: Path):
    project, root, _ = _project(tmp_path)
    task = project.last_task_manager.get_all_tasks()[0]
    task.context["workspace_lease"]["lease_id"] = ""
    with pytest.raises(ValueError, match="without an id"):
        build_project_evidence_bundle(
            project,
            requirement="Build the fixture CLI",
            deliverable_root=root,
            evidence_level="deterministic_orchestration",
        )

    task.context["workspace_lease"]["lease_id"] = "lease-valid"
    task.context["workspace_lease"]["disposition"] = "active-unknown"
    with pytest.raises(ValueError, match="invalid workspace lease disposition"):
        build_project_evidence_bundle(
            project,
            requirement="Build the fixture CLI",
            deliverable_root=root,
            evidence_level="deterministic_orchestration",
        )


def test_rejects_manifest_outside_deliverable_root(tmp_path: Path):
    project, root, _ = _project(tmp_path)
    project.last_delivery["manifest"] = str(tmp_path / "outside.md")

    with pytest.raises(ValueError, match="manifest must be inside"):
        build_project_evidence_bundle(
            project,
            requirement="Build the fixture CLI",
            deliverable_root=root,
            evidence_level="deterministic_orchestration",
        )
