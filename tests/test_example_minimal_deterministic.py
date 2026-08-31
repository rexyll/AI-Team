from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "minimal_deterministic" / "run.py"


def test_minimal_deterministic_example_completes_without_external_provider():
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "task=EXAMPLE-001 status=completed agent=developer" in completed.stdout
    assert completed.stderr == ""
