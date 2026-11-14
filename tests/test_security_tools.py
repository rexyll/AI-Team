import pytest

from security.workspace import resolve_workspace_path, PROJECT_ROOT
from tools.git import git_command
from tools.terminal import _validate_command, run_command


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


def test_terminal_allows_pip_editable_install_but_keeps_eval_flags_blocked():
    _validate_command("python -m pip install -e .")
    _validate_command(r".\\.venv\\Scripts\\python.exe -m pip install -e .")
    _validate_command("pip install -e .")

    with pytest.raises(PermissionError):
        _validate_command("python -e .")
    with pytest.raises(PermissionError):
        _validate_command("python -c print(1)")
