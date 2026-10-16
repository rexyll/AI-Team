"""Deliverable release anchoring: commit the delivery and tag it.

Hands a verified, gated deliverable tree to the host-side Git boundary
(HostGitOperationService) so every accepted delivery gets an immutable
version anchor: a commit of the deliverable files plus an annotated
``release/<project>-<version>`` tag. Re-running with the same version reuses
the existing tag (idempotent), so anchors never duplicate.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from runtime.host_git import HostGitOperationService
from security.workspace import WorkspaceSandbox

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_TAG_SAFE = re.compile(r"[^0-9A-Za-z.\-]+")


def _release_tag(project: str, version: str) -> str:
    safe_project = _TAG_SAFE.sub("-", project.strip().lower()).strip("-")
    if not safe_project:
        raise ValueError("project must contain at least one safe character")
    return f"release/{safe_project}-{version}"


def _git(root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _git_try(root: Path, args: list[str]) -> str | None:
    result = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout if result.returncode == 0 else None


def _current_branch(root: Path) -> str:
    return _git(root, ["branch", "--show-current"]).strip() or "detached"


def find_release_tags(root: str | Path, *, project: str | None = None) -> list[str]:
    """List existing release tags (optionally for one project), oldest first."""
    if project:
        pattern = f"release/{_TAG_SAFE.sub('-', project.strip().lower())}-*"
    else:
        pattern = "release/*"
    output = _git(Path(root), ["tag", "-l", pattern, "--sort=creatordate"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def create_release_anchor(
    root: str | Path,
    *,
    deliverable_dir: str,
    project: str,
    version: str,
) -> dict[str, Any]:
    """Commit the deliverable directory inside ``root`` and tag it as a release.

    The Git sandbox is rooted at ``root`` itself: existence checks, add, and
    commit all resolve through the same boundary the git service enforces.
    Returns tag, commit, branch, and whether an existing tag was reused.
    """
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"repository root does not exist: {root}")
    if not SEMVER_PATTERN.match(version):
        raise ValueError(f"version must be semver (e.g. 1.0.0), got: {version!r}")

    # The Git repository root may sit above the deliverable (e.g. workspace/
    # containing product/); anchor the sandbox at the repository root so the
    # host git boundary can resolve both the repo and the deliverable inside.
    repo_line = _git_try(root, ["rev-parse", "--show-toplevel"])
    if not repo_line:
        raise ValueError("release anchor requires a Git repository")
    repo_root = Path(repo_line.strip()).resolve()

    deliverable = Path(deliverable_dir)
    if not deliverable.is_absolute():
        deliverable = root / deliverable
    deliverable = deliverable.resolve()
    if not deliverable.is_dir():
        raise ValueError(f"deliverable directory does not exist: {deliverable_dir}")

    sandbox = WorkspaceSandbox(repo_root)
    service = HostGitOperationService(sandbox)
    tag = _release_tag(project, version)

    # Idempotent fast path: an existing tag for this version is the anchor.
    existing = _git_try(root, ["rev-parse", "--verify", f"{tag}^{{commit}}"])
    if existing:
        return {
            "tag": tag,
            "commit": existing.strip(),
            "branch": _current_branch(root),
            "reused": True,
        }

    status = service.status(str(repo_root))
    if status.strip():
        # Paths are passed relative to the repository root, which the git
        # service validates inside the repo-rooted sandbox.
        relative = deliverable.relative_to(repo_root).as_posix() or "."
        service.add(str(repo_root), [relative])
        result = service.commit(str(repo_root), f"AI Team delivery: {project} v{version}")
        if "exit_code=0" not in result and "nothing to commit" not in result:
            raise ValueError(f"release commit failed: {result.strip()[:200]}")

    commit = _git(root, ["rev-parse", "HEAD"]).strip()
    _annotate_tag(root, tag, project, version)
    return {
        "tag": tag,
        "commit": commit,
        "branch": _current_branch(root),
        "reused": False,
    }


def _annotate_tag(root: Path, tag: str, project: str, version: str) -> None:
    message = f"AI Team delivery: {project} v{version}"
    if any(ch in tag for ch in '"\n\r'):
        raise ValueError("unsafe tag name")
    _git(root, ["tag", "-a", tag, "-m", message])
