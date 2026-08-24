"""Sandbox-root redirection contracts (structural path enforcement).

Text-level path hints failed across two real models: agents kept writing
relative paths that landed beside - not inside - the mandated directory.
The structural fix redirects the sandbox root before execution so every
relative tool path lands inside the mandated directory by construction.

These contracts pin the redirection semantics, the escape protection
under a redirected root, and the CLI wiring that applies it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import security.workspace as workspace_module
from runtime.plan_constraints import extract_required_paths
from security.workspace import (
    PROJECT_ROOT,
    WorkspaceSandbox,
    anchor_workspace_root,
    get_default_workspace_root,
    set_default_workspace_root,
)


# ---------------------------------------------------------------------------
# anchor rule
# ---------------------------------------------------------------------------


def test_anchor_keeps_all_but_last_segment() -> None:
    base = Path("/base")
    assert anchor_workspace_root(base, "workspace/stringkit") == base / "workspace"
    # 深层约束同样只取父目录链：末段由 agent 写文件时自然生成。
    assert anchor_workspace_root(base, "a/b/c") == base / "a" / "b"


def test_anchor_single_segment_stays_at_base() -> None:
    base = Path("/base")
    assert anchor_workspace_root(base, "output") == base


def test_anchor_normalizes_separators_and_rejects_non_string() -> None:
    assert anchor_workspace_root(Path("/b"), "a\\b") == Path("/b") / "a"
    with pytest.raises(TypeError):
        anchor_workspace_root(Path("/b"), None)


# ---------------------------------------------------------------------------
# Redirection semantics + escape protection
# ---------------------------------------------------------------------------


@pytest.fixture
def redirected(tmp_path, monkeypatch):
    """Install a sandbox rooted at tmp_path/current and restore afterwards."""
    original = workspace_module.DEFAULT_SANDBOX
    current = tmp_path / "current"
    current.mkdir()
    set_default_workspace_root(current)
    yield current
    workspace_module.DEFAULT_SANDBOX = original


def test_setter_redirects_relative_resolution(redirected) -> None:
    target = redirected / "sub"
    target.mkdir()

    resolved = workspace_module.resolve_workspace_path("sub/file.txt")

    assert resolved == target / "file.txt"


def test_escape_protection_survives_redirection(redirected) -> None:
    with pytest.raises(PermissionError):
        workspace_module.resolve_workspace_path("../outside.txt")

    absolute_outside = redirected.parent / "sibling.txt"
    with pytest.raises(PermissionError):
        workspace_module.resolve_workspace_path(absolute_outside)


def test_get_default_root_reflects_redirection(redirected) -> None:
    assert get_default_workspace_root() == redirected.resolve()


def test_setter_rejects_invalid_type() -> None:
    with pytest.raises(TypeError):
        set_default_workspace_root(None)


# ---------------------------------------------------------------------------
# End-to-end chain: requirement text -> extraction -> anchored root
# ---------------------------------------------------------------------------


def test_requirement_paths_drive_the_anchor(tmp_path) -> None:
    requirement = (
        "开发一个工具包：实现 stringkit/utils.py 与 stringkit/cli.py。"
        "所有文件放在 workspace/stringkit/ 目录下。"
    )
    mandated = extract_required_paths(requirement)
    assert mandated == ["workspace/stringkit"]

    anchored = anchor_workspace_root(tmp_path, mandated[0])
    assert anchored == tmp_path / "workspace"

    # 模型写相对路径 'stringkit/utils.py' 时应物理落位于锚定根之下。
    landing = WorkspaceSandbox(anchored).resolve("stringkit/utils.py")
    assert landing == anchored / "stringkit" / "utils.py"
    assert (
        landing.relative_to(tmp_path).as_posix()
        == "workspace/stringkit/utils.py"
    )


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_main_source_wires_projects_base_and_redirection() -> None:
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8-sig"
    )

    assert "--projects-base" in source
    assert "extract_required_paths(requirement)" in source
    assert "set_default_workspace_root(" in source
    assert "anchor_workspace_root(" in source


def test_project_root_points_at_sibling_projects_dir() -> None:
    # The default base is the repo's sibling `projects` directory.
    assert PROJECT_ROOT.name == "projects"
    assert PROJECT_ROOT.parent.name != "projects"
