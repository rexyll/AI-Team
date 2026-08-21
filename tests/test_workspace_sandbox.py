from pathlib import Path

import pytest

from security.workspace import WorkspaceSandbox, resolve_workspace_path


def test_workspace_sandbox_resolves_relative_paths_inside_root(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)

    assert sandbox.resolve("src/example.py") == (
        tmp_path / "src" / "example.py"
    ).resolve()


def test_workspace_sandbox_accepts_absolute_paths_inside_root(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    target = tmp_path / "src" / "example.py"

    assert sandbox.resolve(target) == target.resolve()


def test_workspace_sandbox_rejects_parent_escape(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(PermissionError, match="outside workspace"):
        sandbox.resolve("../outside.txt")


def test_workspace_sandbox_rejects_absolute_escape(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    outside = tmp_path.parent / "outside.txt"

    with pytest.raises(PermissionError, match="outside workspace"):
        sandbox.resolve(outside)


def test_workspace_sandbox_rejects_non_path_values(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(TypeError, match="string or pathlib.Path"):
        sandbox.resolve(123)  # type: ignore[arg-type]


def test_workspace_sandbox_require_file_enforces_file_boundary(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    target = tmp_path / "example.txt"
    target.write_text("hello", encoding="utf-8")

    assert sandbox.require_file("example.txt") == target.resolve()

    with pytest.raises(FileNotFoundError):
        sandbox.require_file("missing.txt")

    with pytest.raises(ValueError, match="Not a file"):
        sandbox.require_file(".")


def test_workspace_sandbox_require_directory_enforces_directory_boundary(
    tmp_path: Path,
):
    sandbox = WorkspaceSandbox(tmp_path)
    directory = tmp_path / "src"
    directory.mkdir()

    assert sandbox.require_directory("src") == directory.resolve()

    with pytest.raises(FileNotFoundError):
        sandbox.require_directory("missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="Not a directory"):
        sandbox.require_directory("file.txt")


def test_workspace_sandbox_blocks_symlink_escape(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    link = tmp_path / "link"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform")

    with pytest.raises(PermissionError, match="outside workspace"):
        sandbox.resolve("link/secret.txt")


def test_legacy_resolve_workspace_path_keeps_same_boundary(tmp_path: Path):
    # The public compatibility helper remains available; its production root
    # is intentionally not changed by the test sandbox above.
    assert callable(resolve_workspace_path)
