from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "review_loop" / "run.py"


def test_review_loop_example_completes_without_external_provider():
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "task=EXAMPLE-REVIEW-001 status=completed" in completed.stdout
    assert "developer_calls=1" in completed.stdout
    assert "review_round=1" in completed.stdout
    assert completed.stderr == ""
