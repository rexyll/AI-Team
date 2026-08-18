import pytest

from security.workspace import resolve_workspace_path, PROJECT_ROOT
from tools.git import git_command
from tools.terminal import run_command


def test_workspace_rejects_path_escape():
    with pytest.raises(PermissionError):
        resolve_workspace_path("..")


def test_git_rejects_workspace_escape():
    with pytest.raises(PermissionError):
        git_command("status", "..")


def test_git_rejects_shell_execution():
    with pytest.raises(PermissionError):
        git_command("status & whoami", ".")


def test_git_rejects_unapproved_subcommand():
    with pytest.raises(PermissionError):
        git_command("push origin main", ".")


def test_terminal_rejects_shell_chaining():
    with pytest.raises(PermissionError):
        run_command("python --version & whoami", ".")


def test_terminal_rejects_unapproved_executable():
    with pytest.raises(PermissionError):
        run_command("whoami", ".")
