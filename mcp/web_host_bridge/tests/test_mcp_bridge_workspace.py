from pathlib import Path

import pytest

from web_host_bridge.workspace import MCPWorkspaceBoundary


def test_relative_path_resolves_inside_workspace(tmp_path):
    target = tmp_path / "runtime"
    target.mkdir()

    boundary = MCPWorkspaceBoundary(tmp_path)
    result = boundary.resolve(
        "runtime",
        require_exists=True,
        expected_kind="directory",
    )

    assert result.absolute_path == target.resolve()
    assert result.relative_path == "runtime"
    assert result.kind == "directory"


def test_parent_escape_is_rejected(tmp_path):
    boundary = MCPWorkspaceBoundary(tmp_path)

    with pytest.raises(PermissionError):
        boundary.resolve("../outside.txt")


def test_absolute_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    boundary = MCPWorkspaceBoundary(tmp_path)

    with pytest.raises(PermissionError):
        boundary.resolve(outside)


def test_git_metadata_is_rejected(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    boundary = MCPWorkspaceBoundary(tmp_path)

    with pytest.raises(PermissionError, match="Git metadata"):
        boundary.resolve(".git/config")


def test_missing_path_can_be_validated_without_existence_requirement(tmp_path):
    boundary = MCPWorkspaceBoundary(tmp_path)

    result = boundary.resolve("future/module.py")

    assert result.relative_path == "future/module.py"
    assert result.kind == "missing"


def test_expected_kind_requires_existing_file(tmp_path):
    source = tmp_path / "module.py"
    source.write_text("x = 1\n", encoding="utf-8")

    boundary = MCPWorkspaceBoundary(tmp_path)
    result = boundary.resolve(
        "module.py",
        require_exists=True,
        expected_kind="file",
    )

    assert result.kind == "file"


def test_symlink_escape_is_rejected_when_supported(tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir(exist_ok=True)
    link = tmp_path / "escape-link"

    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")

    boundary = MCPWorkspaceBoundary(tmp_path)
    with pytest.raises(PermissionError):
        boundary.resolve("escape-link")
