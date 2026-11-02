"""Release phase contracts: version resolution, notes, git anchor, log.

The release anchor exercises the real host-owned Git boundary against a
temporary deliverable directory; no remote operations exist by design.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from runtime.host_git import HostGitOperationService
from runtime.release import (
    RELEASE_NOTES_FILENAME,
    ReleaseRequest,
    build_release_notes,
    load_release_log,
    next_version,
    perform_release,
    resolve_version,
    validate_semver,
)
from security.workspace import WorkspaceSandbox

_NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)


def _context(**overrides: object) -> dict:
    base = {
        "project": "todo",
        "deliverable_dir": "e2e_flat",
        "now": _NOW,
        "requirement_entries": [{"id": "REQ-001", "title": "待办管理", "priority": "必须"}],
        "acceptance": {"verdict": "passed", "total_requirements": 1},
        "integration": {"status": "passed", "rounds": 1, "summary": {"passed": 3}},
        "docs": ["需求规格说明书", "设计文档", "测试结果报告", "部署指引", "用户手册"],
        "task_stats": {"total": 5, "completed": 5},
    }
    base.update(overrides)
    return base


def _service(tmp_path: Path) -> HostGitOperationService:
    return HostGitOperationService(sandbox=WorkspaceSandbox(tmp_path))


def test_validate_semver_accepts_strict_versions():
    assert validate_semver("0.1.0") == "0.1.0"
    assert validate_semver(" 1.2.3 ") == "1.2.3"
    assert validate_semver("1.2.3-rc.1") == "1.2.3-rc.1"
    for bad in ("v1.0.0", "1.2", "1.2.x", "abc", "", "1.2.3.4"):
        with pytest.raises(ValueError):
            validate_semver(bad)


def test_next_version_bumps_patch():
    assert next_version(None) == "0.1.0"
    assert next_version("0.1.0") == "0.1.1"
    assert next_version("1.2.3") == "1.2.4"
    assert next_version("1.2.3-rc.1") == "1.2.4"


def test_resolve_version_explicit_wins_and_duplicates_rejected():
    assert resolve_version(Path("."), "2.0.0", []) == "2.0.0"
    assert resolve_version(Path("."), None, [{"version": "0.1.0"}]) == "0.1.1"
    with pytest.raises(ValueError, match="already been released"):
        resolve_version(Path("."), "0.1.0", [{"version": "0.1.0"}])
    with pytest.raises(ValueError):
        resolve_version(Path("."), "1.0", [])


def test_perform_release_requires_confirmation(tmp_path: Path):
    deliverable = tmp_path / "e2e_flat"
    deliverable.mkdir()
    (deliverable / "todo.py").write_text("x = 1", encoding="utf-8")
    request = ReleaseRequest(
        deliverable_root=str(deliverable), project="todo", auto_release=False,
        confirmer=lambda prompt: False,
    )

    outcome = perform_release(request, git_service=_service(tmp_path), context=_context())

    assert outcome["status"] == "pending"
    assert outcome["version"] == "0.1.0"
    assert not (deliverable / RELEASE_NOTES_FILENAME).exists()
    assert not (deliverable / ".git").exists()


def test_perform_release_confirmed_via_confirmer_anchors_git(tmp_path: Path):
    deliverable = tmp_path / "e2e_flat"
    deliverable.mkdir()
    (deliverable / "todo.py").write_text("x = 1", encoding="utf-8")
    request = ReleaseRequest(
        deliverable_root=str(deliverable), project="todo", auto_release=False,
        confirmer=lambda prompt: True,
    )

    outcome = perform_release(request, git_service=_service(tmp_path), context=_context())

    assert outcome["status"] == "released"
    assert outcome["version"] == "0.1.0"
    assert outcome["tag"] == "v0.1.0"
    assert len(outcome["commit"]) == 40
    notes = (deliverable / RELEASE_NOTES_FILENAME).read_text(encoding="utf-8")
    assert "todo 发布说明（v0.1.0）" in notes
    assert "- REQ-001 待办管理（必须）" in notes
    assert "验收结论：PASSED" in notes
    assert "状态：passed；修复轮次：1；结果统计：3 passed" in notes
    log = load_release_log(deliverable)
    assert len(log) == 1
    assert log[0]["tag"] == "v0.1.0"
    assert log[0]["acceptance_verdict"] == "passed"


def test_perform_release_auto_release_and_version_bump(tmp_path: Path):
    deliverable = tmp_path / "e2e_flat"
    deliverable.mkdir()
    (deliverable / "todo.py").write_text("x = 1", encoding="utf-8")
    service = _service(tmp_path)
    first = ReleaseRequest(deliverable_root=str(deliverable), project="todo", auto_release=True)

    first_outcome = perform_release(first, git_service=service, context=_context())
    second_outcome = perform_release(first, git_service=service, context=_context())

    assert first_outcome["version"] == "0.1.0"
    assert second_outcome["status"] == "released"
    assert second_outcome["version"] == "0.1.1"
    assert second_outcome["tag"] == "v0.1.1"
    log = load_release_log(deliverable)
    assert [entry["version"] for entry in log] == ["0.1.0", "0.1.1"]


def test_perform_release_explicit_duplicate_version_rejected(tmp_path: Path):
    deliverable = tmp_path / "e2e_flat"
    deliverable.mkdir()
    (deliverable / "todo.py").write_text("x = 1", encoding="utf-8")
    service = _service(tmp_path)
    first = ReleaseRequest(deliverable_root=str(deliverable), project="todo", auto_release=True)
    perform_release(first, git_service=service, context=_context())

    duplicate = ReleaseRequest(
        deliverable_root=str(deliverable), project="todo", version="0.1.0", auto_release=True,
    )

    with pytest.raises(ValueError, match="already been released"):
        perform_release(duplicate, git_service=service, context=_context())


def test_perform_release_corrupt_log_fails_closed(tmp_path: Path):
    deliverable = tmp_path / "e2e_flat"
    deliverable.mkdir()
    (deliverable / RELEASE_NOTES_FILENAME).parent.mkdir(parents=True, exist_ok=True)
    (deliverable / "release_log.json").write_text("{not json", encoding="utf-8")
    request = ReleaseRequest(deliverable_root=str(deliverable), project="todo", auto_release=True)

    with pytest.raises(json.JSONDecodeError):
        perform_release(request, git_service=_service(tmp_path), context=_context())


def test_perform_release_rejects_missing_deliverable(tmp_path: Path):
    request = ReleaseRequest(
        deliverable_root=str(tmp_path / "missing"), project="todo", auto_release=True,
    )

    with pytest.raises(ValueError, match="does not exist"):
        perform_release(request, git_service=_service(tmp_path), context=_context())


def test_build_release_notes_without_structured_requirements():
    notes = build_release_notes(
        project="todo",
        version="0.1.0",
        created_at="2026-11-02T12:00:00Z",
        context={"deliverable_dir": ".", "requirement_entries": [], "acceptance": None},
    )

    assert "（无结构化需求编号）" in notes
    assert "验收结论：未执行" in notes
    assert "无集成回归证据" in notes
