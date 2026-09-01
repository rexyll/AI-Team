from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "security",
        (sys.executable, "tools/run_security_regression.py"),
    ),
    (
        "extension-boundary",
        (
            sys.executable,
            "-m",
            "pytest",
            "tests/test_plugin_api.py",
            "tests/test_plugin_extension_compatibility.py",
            "tests/test_extension_examples_contract.py",
            "-q",
        ),
    ),
    (
        "persistence-recovery",
        (
            sys.executable,
            "-m",
            "pytest",
            "tests/test_workflow_recovery_state_consistency.py",
            "tests/test_workflow_event_query_contract.py",
            "tests/test_workflow_event_end_to_end_contract.py",
            "-q",
        ),
    ),
    (
        "full-regression",
        (sys.executable, "-m", "pytest", "-q"),
    ),
)


def main() -> int:
    print("AI-Team production readiness gate")
    print(f"repository={ROOT}")

    for name, command in GATES:
        print(f"\n[{name}]")
        print("$", " ".join(command))
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            print(f"gate_failed={name} exit_code={completed.returncode}", file=sys.stderr)
            return completed.returncode
        print(f"gate_passed={name}")

    print("\nproduction_readiness=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
