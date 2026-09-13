from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from runtime.tool_errors import classify_tool_exception
from security.process_sandbox import (
    WindowsProcessJob,
    create_process_job,
    process_job_supported,
    wait_for_process_exit,
)
from tools.terminal import run_command

pytestmark = pytest.mark.skipif(
    not process_job_supported(),
    reason="Windows Job Object containment requires Windows",
)

PYTHON = sys.executable


def test_normal_command_completes_inside_job(tmp_path):
    job = WindowsProcessJob()

    process = subprocess.Popen(
        [PYTHON, "-c", "print('sandbox-ok')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
    )
    job.assign(process)
    stdout, _ = process.communicate(timeout=30)
    job.close()

    assert process.returncode == 0
    assert b"sandbox-ok" in stdout


def test_memory_limit_rejects_runaway_allocation(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TEAM_SANDBOX_MEMORY_MB", "256")
    job = WindowsProcessJob()

    runaway = subprocess.Popen(
        [PYTHON, "-c", "blob = bytearray(512 * 1024 * 1024); print('allocated')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
    )
    job.assign(runaway)
    stdout, _ = runaway.communicate(timeout=60)
    job.close()

    assert runaway.returncode != 0
    assert b"allocated" not in stdout


def test_memory_limit_allows_normal_workload(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TEAM_SANDBOX_MEMORY_MB", "256")
    job = WindowsProcessJob()

    modest = subprocess.Popen(
        [PYTHON, "-c", "blob = bytearray(32 * 1024 * 1024); print('fine')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
    )
    job.assign(modest)
    stdout, _ = modest.communicate(timeout=60)
    job.close()

    assert modest.returncode == 0
    assert b"fine" in stdout


def test_active_process_limit_blocks_runaway_process_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TEAM_SANDBOX_MAX_PROCESSES", "3")
    spawner = tmp_path / "spawner.py"
    spawner.write_text(
        textwrap.dedent(
            """
            import subprocess, sys
            succeeded = 0
            children = []
            for _ in range(5):
                try:
                    children.append(subprocess.Popen(
                        [sys.executable, "-c", "import time; time.sleep(5)"]
                    ))
                    succeeded += 1
                except OSError:
                    break
            print(succeeded, flush=True)
            for child in children:
                child.wait()
            """
        ),
        encoding="utf-8",
    )
    job = WindowsProcessJob()

    process = subprocess.Popen(
        [PYTHON, str(spawner)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
    )
    job.assign(process)
    stdout, _ = process.communicate(timeout=60)
    job.close()

    # Parent plus at most two concurrent children fit the limit of 3.
    assert int(stdout.decode().strip()) <= 2


def test_timeout_terminates_whole_process_tree(tmp_path):
    child_script = tmp_path / "child.py"
    grandchild_pid_file = tmp_path / "grandchild.pid"
    child_script.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys
            grandchild = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            with open(r"{grandchild_pid_file}", "w", encoding="utf-8") as handle:
                handle.write(str(grandchild.pid))
            grandchild.wait()
            """
        ),
        encoding="utf-8",
    )
    job = WindowsProcessJob()

    process = subprocess.Popen(
        [PYTHON, str(child_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
    )
    job.assign(process)
    with pytest.raises(subprocess.TimeoutExpired):
        process.communicate(timeout=2)
    job.terminate()
    process.wait()
    job.close()

    assert grandchild_pid_file.exists()
    grandchild_pid = int(grandchild_pid_file.read_text(encoding="utf-8"))
    assert wait_for_process_exit(grandchild_pid, timeout_ms=5000) is True


def test_terminal_run_command_runs_inside_sandbox(tmp_path):
    from security.workspace import WorkspaceSandbox

    (tmp_path / "hello.py").write_text("print('contained')\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    output = run_command("python hello.py", cwd=".", sandbox=sandbox, timeout=60)

    assert output.startswith("exit_code=0")
    assert "contained" in output


def test_terminal_run_command_timeout_raises_timeout_error(tmp_path):
    from security.workspace import WorkspaceSandbox

    (tmp_path / "slow.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(TimeoutError, match="timed out after 1 seconds"):
        run_command("python slow.py", cwd=".", sandbox=sandbox, timeout=1)


def test_builtin_timeout_classifies_as_tool_timeout():
    error = classify_tool_exception(TimeoutError("Command timed out after 1 seconds"))

    assert error.code == "TOOL_TIMEOUT"
    assert error.category == "timeout"


def test_create_process_job_returns_none_without_support(monkeypatch):
    import security.process_sandbox as module

    monkeypatch.setattr(module, "process_job_supported", lambda: False)
    assert create_process_job() is None
