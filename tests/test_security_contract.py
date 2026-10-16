from __future__ import annotations

from pathlib import Path

import pytest

from security.tool_guard import ToolArgumentValidationError, validate_tool_arguments
from security.tool_permission import (
    EXECUTE,
    READ,
    WRITE,
    ToolPermissionError,
    ToolPermissionPolicy,
)
from security.workspace import WorkspaceSandbox
from tools.git import git_command
from tools.terminal import run_command


def _schema() -> dict:
    return {
        "function": {
            "name": "read_file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "encoding": {"type": "string"},
                },
                "required": ["path"],
            },
        }
    }


def test_schema_validation_rejects_unknown_and_missing_arguments():
    with pytest.raises(ToolArgumentValidationError, match="unknown argument"):
        validate_tool_arguments(lambda path: path, {"path": "a", "admin": True}, _schema())

    with pytest.raises(ToolArgumentValidationError, match="missing required"):
        validate_tool_arguments(lambda path: path, {"encoding": "utf-8"}, _schema())


def test_schema_validation_rejects_mistyped_arguments_before_execution():
    with pytest.raises(ToolArgumentValidationError, match="must be of type string"):
        validate_tool_arguments(lambda path: path, {"path": 123}, _schema())


def test_permission_policy_is_deny_by_default_and_validates_capabilities():
    policy = ToolPermissionPolicy({"reader": [READ], "writer": [READ, WRITE]})

    assert policy.allows("reader", READ)
    assert not policy.allows("reader", WRITE)
    assert not policy.allows("unknown", EXECUTE)

    with pytest.raises(ToolPermissionError, match="not permitted"):
        policy.require("reader", WRITE)

    with pytest.raises(ValueError, match="Unknown tool capability"):
        policy.allows("reader", "network")


def test_permission_policy_rejects_unknown_grants():
    with pytest.raises(ValueError, match="Unknown tool capability"):
        ToolPermissionPolicy({"reader": ["network"]})


def test_workspace_rejects_absolute_and_nested_parent_escape(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = WorkspaceSandbox(root)

    assert sandbox.resolve("src/file.py") == (root / "src/file.py").resolve()

    with pytest.raises(PermissionError):
        sandbox.resolve("../outside.txt")

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError):
        sandbox.resolve(outside)


def test_workspace_require_helpers_enforce_file_and_directory_types(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    file_path = root / "file.txt"
    directory = root / "directory"
    file_path.write_text("data", encoding="utf-8")
    directory.mkdir()

    sandbox = WorkspaceSandbox(root)
    assert sandbox.require_file("file.txt") == file_path.resolve()
    assert sandbox.require_directory("directory") == directory.resolve()

    with pytest.raises(ValueError, match="Not a file"):
        sandbox.require_file("directory")
    with pytest.raises(ValueError, match="Not a directory"):
        sandbox.require_directory("file.txt")
    with pytest.raises(FileNotFoundError):
        sandbox.require_file("missing.txt")


def test_terminal_blocks_command_evaluation_and_shell_expansion():
    for command in (
        "python -c print(1)",
        "python --exec test.py",
        "python $(whoami)",
        "python ${HOME}",
        "python $env:PATH",
        "python > output.txt",
    ):
        with pytest.raises(PermissionError):
            run_command(command, ".")


def test_terminal_rejects_non_allowlisted_executable_before_execution():
    with pytest.raises(PermissionError, match="Executable is not allowed"):
        run_command("cmd.exe /c whoami", ".")


def test_git_blocks_configuration_and_transport_escape_options():
    for command in (
        "status --git-dir C:\\secret",
        "status --work-tree C:\\secret",
        "status --upload-pack evil",
        "status -C C:\\secret",
        "status --config-env core.sshCommand=evil",
    ):
        with pytest.raises(PermissionError):
            git_command(command, ".")


def test_git_rejects_shell_metacharacters_before_execution():
    for command in (
        "status && whoami",
        "status | whoami",
        "status; whoami",
        "status > out.txt",
        "status `whoami`",
    ):
        with pytest.raises(PermissionError):
            git_command(command, ".")


def test_git_tag_and_init_allowlist_keeps_escape_options_blocked():
    # tag/init entered the allowlist for release anchoring; escape hatches stay closed.
    for command in (
        "tag -C C:\\secret",
        "tag --upload-pack evil",
        "init --template=/evil",
        "init --separate-git-dir C:\\secret",
    ):
        with pytest.raises(PermissionError):
            git_command(command, ".")
