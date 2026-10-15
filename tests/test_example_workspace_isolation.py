from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "workspace_isolation" / "run.py"


def test_workspace_isolation_example_blocks_cross_workspace_access():
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert "workspace-a=project-a" in completed.stdout
    assert "workspace-b=project-b" in completed.stdout
    assert "cross-workspace-access=blocked" in completed.stdout
