"""End-to-end contract tests for the deliverable release anchor.

Uses a real Git repository (git init via subprocess) and the real host Git
service — no mocks — to verify that a delivery can be committed and tagged,
and that the anchor is discoverable afterwards.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.release_anchor import create_release_anchor, find_release_tags
from security.workspace import WorkspaceSandbox


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture()
def repo(tmp_path: Path):
    root = tmp_path
    _git(root, "init")
    _git(root, "config", "user.email", "ai-team@example.invalid")
    _git(root, "config", "user.name", "AI Team")
    root.joinpath("deliverable").mkdir()
    (root / "deliverable" / "todo.py").write_text("print('v')\n", encoding="utf-8")
    return root


def test_create_release_anchor_commits_and_tags(repo: Path):
    service = _make_service(repo)
    anchor = create_release_anchor(
        repo, deliverable_dir="deliverable", project="todo", version="1.0.0",
    )

    assert anchor["commit"]
    assert anchor["tag"] == "release/todo-1.0.0"
    assert anchor["branch"]
    # Tag points at HEAD and is annotated (deref the tag object to its commit).
    assert _git(repo, "rev-parse", "HEAD").strip() == _git(repo, "rev-parse", "release/todo-1.0.0^{commit}").strip()
    assert _git(repo, "tag", "-l").strip() == "release/todo-1.0.0"
    assert "AI Team delivery: todo v1.0.0" in _git(repo, "tag", "-l", "-n1")


def test_anchor_idempotent_on_rerun(repo: Path):
    service = _make_service(repo)
    first = create_release_anchor(
        repo, deliverable_dir="deliverable", project="todo", version="1.0.0",
    )
    # Second run with no changes: same commit, no duplicate tag error.
    repo.joinpath("deliverable", "todo.py").write_text("print('v')\n", encoding="utf-8")
    second = create_release_anchor(
        repo, deliverable_dir="deliverable", project="todo", version="1.0.0",
    )

    assert second["commit"] == first["commit"] or _git(repo, "status", "--short").strip() == ""
    tags = _git(repo, "tag", "-l").split()
    assert tags.count("release/todo-1.0.0") == 1


def test_anchor_requires_existing_deliverable(repo: Path):
    service = _make_service(repo)
    with pytest.raises(ValueError, match="deliverable"):
        create_release_anchor(
            repo, deliverable_dir="missing", project="todo", version="1.0.0",
        )


def test_anchor_validates_version(repo: Path):
    with pytest.raises(ValueError, match="version"):
        create_release_anchor(
            repo, deliverable_dir="deliverable", project="todo", version="not a version; rm -rf /",
        )


def _make_service(root: Path):
    from runtime.host_git import HostGitOperationService
    from security.workspace import WorkspaceSandbox

    return HostGitOperationService(WorkspaceSandbox(root))
