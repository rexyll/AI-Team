from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "operational_observability" / "run.py"


def test_operational_observability_example_runs_without_external_provider():
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "workflow total=3 completed=1 failed=1 active=1 success_rate=0.33" in completed.stdout
    assert "alert=failed-tasks severity=warning" in completed.stdout
    assert completed.stderr == ""
