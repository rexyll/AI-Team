from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.delivery_manifest import write_delivery_manifest
from runtime.project_evidence_bundle import (
    _acceptance_summary,
    _artifact_summary,
    _canonical_json,
    _duration_seconds,
    _file_sha256,
    _gate_summary,
    _integration_summary,
    _task_summaries,
    _tool_record_summary,
    _workspace_summary,
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
        "acceptance": {
            "verdict": "passed",
            "traceability_verdict": "passed",
            "executable_verdict": "passed",
            "gaps": [],
            "warnings": [],
            "test_count": 1,
            "requirements": [{
                "req_id": "REQ-001",
                "tests": [{
                    "test_id": "AT-001",
                    "selector": "tests.test_app::test_accepts_input",
                    "status": "passed",
                }],
            }],
        },
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
    acceptance = bundle["gates"]["acceptance"]
    assert acceptance["executable_verdict"] == "passed"
    assert acceptance["requirements"][0]["tests"][0]["test_id"] == "AT-001"
    assert acceptance["requirements"][0]["tests"][0]["selector"] == "tests.test_app::test_accepts_input"
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



def _tool_record(**overrides):
    record = {
        "execution_id": "exec-qa-001",
        "task_id": "QA-001",
        "agent_role": "qa",
        "tool_name": "run_command",
        "started_at": "2026-11-15T10:00:00+00:00",
        "completed_at": "2026-11-15T10:00:03+00:00",
        "status": "completed",
        "arguments": {"command": "python -m sample_app.cli --value 0"},
    }
    record.update(overrides)
    return record


def test_canonical_json_and_duration_reject_non_finite_or_unusable_values():
    assert json.loads(_canonical_json({"b": 2, "a": 1})) == {"a": 1, "b": 2}
    with pytest.raises(TypeError, match="finite JSON data"):
        _canonical_json(float("nan"))

    assert _duration_seconds(None, "2026-11-15T10:00:00Z") is None
    assert _duration_seconds("not-a-date", "2026-11-15T10:00:00Z") is None
    assert _duration_seconds(
        "2026-11-15T10:00:00", "2026-11-15T10:00:01"
    ) is None
    assert _duration_seconds(
        "2026-11-15T10:00:02Z", "2026-11-15T10:00:01Z"
    ) is None


def test_file_digest_returns_none_for_missing_directory_and_symlink(tmp_path: Path):
    assert _file_sha256(tmp_path / "missing.bin") is None
    assert _file_sha256(tmp_path) is None
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    assert _file_sha256(source) == hashlib.sha256(b"content").hexdigest()
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable: {type(exc).__name__}")
    assert _file_sha256(link) is None


def test_tool_record_summary_accepts_prehashed_qa_metadata_and_rejects_invalid_records():
    summary = _tool_record_summary(_tool_record(arguments_sha256="a" * 64))
    assert summary["role"] == "qa"
    assert summary["arguments_sha256"] == "a" * 64
    assert summary["duration_seconds"] == 3.0

    with pytest.raises(ValueError, match="arguments_sha256 is invalid"):
        _tool_record_summary(_tool_record(arguments_sha256="not-a-hash"))
    with pytest.raises(ValueError, match="missing execution_id"):
        _tool_record_summary(_tool_record(execution_id=""))
    with pytest.raises(ValueError, match="status must be non-empty"):
        _tool_record_summary(_tool_record(status=""))
    with pytest.raises(ValueError, match="completed_at must be a string"):
        _tool_record_summary(_tool_record(completed_at=42))


def test_workspace_summary_covers_issued_merged_discarded_and_missing_lease():
    assert _workspace_summary({}, "TASK-1") is None
    issued = _workspace_summary({
        "workspace_lease": {
            "lease_id": "lease-1",
            "task_id": "TASK-1",
            "disposition": "issued",
        },
        "workspace_environment": {
            "status": "passed",
            "adapter": "python",
            "created": True,
        },
    }, "TASK-1")
    assert issued["disposition"] == "issued"
    assert issued["environment"]["created"] is True

    discarded = _workspace_summary({
        "workspace_lease": {
            "lease_id": "lease-2",
            "disposition": "discarded",
        },
        "workspace_merge": {"changed": ["a"], "added": ["b"], "deleted": ["c"]},
    }, "TASK-2")
    assert discarded["merge"]["deleted"] == ["c"]

    with pytest.raises(ValueError, match="without an id"):
        _workspace_summary({
            "workspace_lease": {"lease_id": " ", "disposition": "merged"}
        }, "TASK-3")


def test_task_summaries_report_incomplete_and_not_applicable_workspace_states():
    project = SimpleNamespace(
        last_task_manager=SimpleNamespace(get_all_tasks=lambda: [
            SimpleNamespace(
                id="TASK-A",
                role="architect",
                status="completed",
                dependencies=[],
                title="Design",
                description="Design interfaces",
                context={},
                test_result={"status": "passed"},
                review_result={"verdict": "approved"},
            ),
            SimpleNamespace(
                id="TASK-D",
                role="developer",
                status="failed",
                dependencies=["TASK-A"],
                title="Implement",
                description="Implementation failed",
                context={},
            ),
        ])
    )
    summaries, workspace, records = _task_summaries(project)
    assert summaries[0]["tester"] == {"status": "passed"}
    assert summaries[0]["reviewer"] == {"verdict": "approved"}
    assert summaries[1]["terminal"] is True
    assert workspace["status"] == "incomplete"
    assert workspace["leases_incomplete"] == 1
    assert records == []

    no_developer = SimpleNamespace(
        last_task_manager=SimpleNamespace(get_all_tasks=lambda: [
            SimpleNamespace(
                id="TASK-A", role="architect", status="completed",
                dependencies=[], title="", description="", context={}
            )
        ])
    )
    _, no_workspace, _ = _task_summaries(no_developer)
    assert no_workspace["status"] == "not_applicable"

    with pytest.raises(ValueError, match="no completed task manager"):
        _task_summaries(SimpleNamespace(last_task_manager=None))


def test_task_summaries_reject_invalid_dependencies_and_tool_history():
    invalid_dependencies = SimpleNamespace(
        id="TASK-1", role="developer", status="completed",
        dependencies=("TASK-0",), title="", description="", context={}
    )
    with pytest.raises(ValueError, match="dependencies must be a list"):
        _task_summaries(SimpleNamespace(
            last_task_manager=SimpleNamespace(get_all_tasks=lambda: [invalid_dependencies])
        ))

    malformed_history = SimpleNamespace(
        id="TASK-1", role="architect", status="completed",
        dependencies=[], title="", description="",
        context={"tool_execution_history": ["not-a-record"]},
    )
    with pytest.raises(ValueError, match="malformed tool evidence"):
        _task_summaries(SimpleNamespace(
            last_task_manager=SimpleNamespace(get_all_tasks=lambda: [malformed_history])
        ))

    conflicting = SimpleNamespace(
        id="TASK-1", role="architect", status="completed",
        dependencies=[], title="", description="",
        context={"tool_execution_history": [
            _tool_record(task_id="TASK-1"),
            _tool_record(task_id="TASK-1", arguments={"command": "different"}),
        ]},
    )
    with pytest.raises(ValueError, match="conflicting tool evidence"):
        _task_summaries(SimpleNamespace(
            last_task_manager=SimpleNamespace(get_all_tasks=lambda: [conflicting])
        ))


def test_integration_and_gate_summaries_handle_optional_and_partial_inputs():
    assert _integration_summary(None) == (None, [])
    integration, tools = _integration_summary({
        "status": "passed",
        "suite": {
            "status": "passed",
            "exit_code": 0,
            "summary": {"passed": 1},
            "test_cases": [
                {"selector": "tests.test_x::test_ok", "status": "passed"},
                "malformed",
            ],
        },
        "static": {
            "status": "passed",
            "tools": {"ruff": {"status": "passed", "enforced": True}, "bad": None},
        },
        "adapter": {
            "status": "passed",
            "adapter": "node",
            "signals": ["package-lock.json"],
            "actions": {"test": {"status": "passed", "exit_code": 0}, "bad": None},
            "tool_execution_history": [_tool_record()],
        },
    })
    assert integration["suite"]["test_case_count"] == 2
    assert integration["static"]["tools"]["ruff"]["enforced"] is True
    assert integration["adapter"]["actions"]["test"]["status"] == "passed"
    assert tools[0]["role"] == "qa"
    assert _gate_summary(None) is None

    gate = _gate_summary({
        "status": "completed",
        "verdict": "QA_PASSED",
        "gaps": ["a", "b"],
        "executed_tool_calls": 2,
        "tool_execution_history": [_tool_record()],
    })
    assert gate["gaps_count"] == 2
    assert gate["tool_invocation_count"] == 1
    assert gate["tool_invocation_statuses"][0]["tool"] == "run_command"


def test_acceptance_summary_and_artifact_summary_handle_missing_artifacts(tmp_path: Path):
    assert _acceptance_summary(None) is None
    acceptance = _acceptance_summary({
        "verdict": "blocked",
        "traceability_verdict": "failed",
        "executable_verdict": "not_executed",
        "requirements": [{"req_id": "REQ-001", "tests": [
            {"test_id": "AT-001", "selector": "tests.test_x::test_y", "status": "not_executed"}
        ]}],
    })
    assert acceptance["requirements"][0]["tests"][0]["status"] == "not_executed"

    root = tmp_path / "deliverable"
    root.mkdir()
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    summary = _artifact_summary({
        "package": {"archive": str(tmp_path / "missing.zip"), "checksum": "0" * 64},
        "build_evidence": {"status": "available", "path": str(tmp_path / "missing-build.json")},
        "sbom": {"status": "available", "path": str(tmp_path / "missing-sbom.json")},
        "provenance": {"status": "unavailable"},
    }, root)
    assert summary["manifest"]["status"] == "unavailable"
    assert summary["package"]["status"] == "unavailable"
    assert summary["package"]["recorded_sha256_matches"] is None
    assert summary["sidecars"]["build_evidence"]["sha256"] is None
    assert summary["sidecars"]["provenance"]["filename"] is None
    assert summary["smoke"] is None


def test_bundle_builder_rejects_invalid_top_level_inputs(tmp_path: Path):
    project, root, _ = _project(tmp_path)
    with pytest.raises(ValueError, match="requirement must be a non-empty"):
        build_project_evidence_bundle(
            project, requirement=" ", deliverable_root=root,
            evidence_level="deterministic_orchestration"
        )
    with pytest.raises(ValueError, match="unsupported evidence_level"):
        build_project_evidence_bundle(
            project, requirement="req", deliverable_root=root, evidence_level="unknown"
        )
    with pytest.raises(ValueError, match="deliverable root does not exist"):
        build_project_evidence_bundle(
            project, requirement="req", deliverable_root=tmp_path / "missing",
            evidence_level="deterministic_orchestration"
        )
    project.last_delivery = None
    with pytest.raises(ValueError, match="no delivery evidence"):
        build_project_evidence_bundle(
            project, requirement="req", deliverable_root=root,
            evidence_level="deterministic_orchestration"
        )


def test_bundle_validator_rejects_wrong_schema_and_privacy_claims(tmp_path: Path):
    project, root, _ = _project(tmp_path)
    bundle = build_project_evidence_bundle(
        project, requirement="Build a fixture", deliverable_root=root,
        evidence_level="deterministic_orchestration"
    )
    unsupported = dict(bundle)
    unsupported["schema_version"] = 99
    with pytest.raises(ValueError, match="unsupported project evidence schema"):
        validate_project_evidence_bundle(unsupported)

    privacy_violation = dict(bundle)
    privacy_violation["privacy"] = dict(bundle["privacy"])
    privacy_violation["privacy"]["secret_values_included"] = True
    privacy_violation["evidence_sha256"] = "0" * 64
    # Fix the digest so the privacy validator, rather than the digest check, is exercised.
    from runtime.project_evidence_bundle import _sha256_value
    unsigned = dict(privacy_violation)
    unsigned.pop("evidence_sha256")
    privacy_violation["evidence_sha256"] = _sha256_value(unsigned)
    with pytest.raises(ValueError, match="privacy declaration is invalid"):
        validate_project_evidence_bundle(privacy_violation)
