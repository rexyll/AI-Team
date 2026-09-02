from pathlib import Path

from tools.terminal import _resolve_workspace_executable


def test_workspace_virtualenv_executable_is_preferred_for_bare_command(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    pytest_exe = scripts / "pytest.exe"
    pytest_exe.write_text("fixture", encoding="utf-8")
    resolved = _resolve_workspace_executable("pytest -q", tmp_path)
    assert resolved == f'"{pytest_exe}" -q' or resolved == f"{pytest_exe} -q"


def test_workspace_virtualenv_resolution_preserves_arguments(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    python_exe = scripts / "python.exe"
    python_exe.write_text("fixture", encoding="utf-8")
    resolved = _resolve_workspace_executable(
        "  python -m pytest tests/test_terminal.py -q",
        tmp_path,
    )
    assert resolved.startswith(f"  {python_exe}")
    assert resolved.endswith(" -m pytest tests/test_terminal.py -q")


def test_explicit_path_is_not_rewritten(tmp_path: Path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    pytest_exe = scripts / "pytest.exe"
    pytest_exe.write_text("fixture", encoding="utf-8")
    command = f'"{pytest_exe}" -q'
    assert _resolve_workspace_executable(command, tmp_path) == command


def test_missing_workspace_executable_falls_back_to_original_command(
    tmp_path: Path,
) -> None:
    assert _resolve_workspace_executable("pytest -q", tmp_path) == "pytest -q"


def test_unallowlisted_executable_is_not_resolved(tmp_path: Path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    evil_exe = scripts / "evil.exe"
    evil_exe.write_text("fixture", encoding="utf-8")
    assert _resolve_workspace_executable("evil -q", tmp_path) == "evil -q"
