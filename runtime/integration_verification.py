"""Product-level integration & regression verification.

Treats the deliverable as a whole: after every product task completes (and
before documentation/packaging), the deliverable's full test suite is executed
from a fresh copy of the files — the same deployed-layout parity the packaging
smoke uses, applied as a pre-release gate. The structured result flows into
the delivery context (test report) and the release gate.

The suite is the product-level regression ground truth. A failed suite feeds a
bounded rework loop (orchestrator-side): developer rework tasks repair the
deliverable through the canonical TaskWorkflow, then the suite runs again.
Exhausted rounds are reported honestly as FAILED — a red suite never silently
passes through.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime.deployment import find_test_files, stage_deliverable_copy

DEFAULT_INTEGRATION_TIMEOUT = 300.0

_SUMMARY_LINE = re.compile(r"^\s*(?P<counts>.+?)(?:, )? in (?P<seconds>\d+(?:\.\d+)?)s\s*$")
_COUNT_TOKEN = re.compile(r"(\d+) (passed|failed|errors?|skipped|xpassed|xfailed)\b")
_FAILED_NAME = re.compile(r"^FAILED (\S+?)(?: - .*)?$")

_MAX_FAILED_NAMES = 20


def parse_pytest_summary(output: str) -> dict[str, int] | None:
    """Parse the trailing pytest summary line into outcome counts.

    Returns ``None`` when no summary line is found (crashed interpreter,
    collection error banner without a counts line, etc.). The exit code stays
    the authoritative pass/fail signal; the parsed counts are evidence only.
    """
    if not output:
        return None
    for line in reversed(output.splitlines()):
        match = _SUMMARY_LINE.match(line)
        if match is None:
            continue
        counts = _COUNT_TOKEN.findall(match.group("counts"))
        if not counts:
            continue
        summary: dict[str, int] = {}
        for value, token in counts:
            key = "error" if token.startswith("error") else token
            summary[key] = summary.get(key, 0) + int(value)
        return summary
    return None


def extract_failed_tests(output: str) -> list[str]:
    """Return failed test ids from pytest's short summary (``FAILED name`` lines)."""
    if not output:
        return []
    names: list[str] = []
    for line in output.splitlines():
        match = _FAILED_NAME.match(line.strip())
        if match is not None:
            names.append(match.group(1))
            if len(names) >= _MAX_FAILED_NAMES:
                break
    return names


def run_integration_suite(
    deliverable_root: str | Path,
    *,
    python: str = sys.executable,
    timeout: float = DEFAULT_INTEGRATION_TIMEOUT,
) -> dict[str, Any]:
    """Run the deliverable's full test suite from a fresh copy of the files.

    The suite runs with the working directory set to a fresh staging copy so
    the verification exercises the deployed layout, not the authoring
    workspace. Returns a detached structured-evidence record; the status is
    ``passed``/``failed`` from the suite exit code, or ``skipped`` when the
    deliverable does not exist or contains no test files. An empty or absent
    deliverable is still caught downstream by the fail-closed packaging gate.
    """
    root = Path(deliverable_root)
    if not root.is_dir():
        return {
            "status": "skipped",
            "reason": f"deliverable root does not exist: {root}",
            "test_files": [],
            "command": None,
            "exit_code": None,
            "duration_seconds": None,
            "summary": None,
            "failed_tests": [],
            "output_tail": "",
        }
    test_files = find_test_files(root)
    if not test_files:
        return {
            "status": "skipped",
            "reason": "no test files found",
            "test_files": [],
            "command": None,
            "exit_code": None,
            "duration_seconds": None,
            "summary": None,
            "failed_tests": [],
            "output_tail": "",
        }

    staging = stage_deliverable_copy(root)
    command = [python, "-m", "pytest", *test_files, "-q", "--tb=short", "-p", "no:cacheprovider"]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(staging),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "reason": f"integration suite timed out after {timeout} seconds",
            "test_files": test_files,
            "command": " ".join(command),
            "exit_code": None,
            "duration_seconds": round(time.monotonic() - started, 2),
            "summary": None,
            "failed_tests": [],
            "output_tail": "",
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    duration = round(time.monotonic() - started, 2)
    output = (completed.stdout or b"").decode("utf-8", errors="replace")
    errors = (completed.stderr or b"").decode("utf-8", errors="replace")
    tail = output[-3500:] if output else ""
    if errors.strip():
        tail = (tail + "\n[stderr]\n" + errors[-1500:]) if tail else errors[-1500:]
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "reason": None,
        "test_files": test_files,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "summary": parse_pytest_summary(output),
        "failed_tests": extract_failed_tests(output),
        "output_tail": tail[-4000:],
    }
