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

import importlib.util
import re
import xml.etree.ElementTree as ET
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Sequence

from runtime.deployment import find_test_files, stage_deliverable_copy

DEFAULT_INTEGRATION_TIMEOUT = 300.0
DEFAULT_STATIC_TIMEOUT = 120.0
# Conservative "broken code" rule set, pinned explicitly so gate semantics
# stay deterministic across ruff versions: syntax errors (E9), invalid
# comparisons/asserts (F63), undefined names (F82) — never style rules.
_STATIC_TOOL_ARGS = {
    "ruff": ["check", ".", "--select", "E9,F63,F7,F82", "--no-cache"],
    "mypy": [
        "--ignore-missing-imports",
        "--cache-dir",
        str(Path(tempfile.gettempdir()) / "ai-team-mypy-cache"),
    ],
}

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


def parse_junit_test_cases(report_path: str | Path) -> list[dict[str, Any]]:
    """Extract exact JUnit selectors and outcomes from a pytest report."""
    path = Path(report_path)
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    records: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        classname = case.attrib.get("classname", "").strip()
        name = case.attrib.get("name", "").strip()
        if not classname or not name:
            continue
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        status = "failed" if failure is not None or error is not None else "skipped" if skipped is not None else "passed"
        detail = failure if failure is not None else error if error is not None else skipped
        records.append({
            "selector": f"{classname}::{name}",
            "status": status,
            "duration_seconds": float(case.attrib.get("time", "0") or 0),
            "summary": (detail.attrib.get("message") or (detail.text or "").strip())[:500] if detail is not None else None,
        })
    return records


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
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    junit_report = staging / ".ai-team-junit.xml"
    command.append(f"--junitxml={junit_report}")
    try:
        completed = subprocess.run(
            command,
            cwd=str(staging),
            capture_output=True,
            timeout=timeout,
        )
        test_cases = parse_junit_test_cases(junit_report)
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "reason": f"integration suite timed out after {timeout} seconds",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "test_cases": [],
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
    completed_at = datetime.now(timezone.utc).isoformat()
    output = (completed.stdout or b"").decode("utf-8", errors="replace")
    errors = (completed.stderr or b"").decode("utf-8", errors="replace")
    tail = output[-3500:] if output else ""
    if errors.strip():
        tail = (tail + "\n[stderr]\n" + errors[-1500:]) if tail else errors[-1500:]
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "reason": None,
        "started_at": started_at,
        "completed_at": completed_at,
        "test_cases": test_cases,
        "test_files": test_files,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "summary": parse_pytest_summary(output),
        "failed_tests": extract_failed_tests(output),
        "output_tail": tail[-4000:],
    }


def run_static_quality_gate(
    deliverable_root: str | Path,
    *,
    python: str = sys.executable,
    timeout: float = DEFAULT_STATIC_TIMEOUT,
    run_mypy: bool = False,
    enforce_mypy: bool = False,
    tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run deterministic static checks (ruff, optionally mypy) on the deliverable.

    ruff is enforced with a pinned conservative "broken code" rule set
    (E9/F63/F7/F82: syntax errors, invalid comparisons, undefined names —
    never style rules); mypy is opt-in (``run_mypy``) and recorded-only
    unless ``enforce_mypy`` is set. A tool that is not installed is reported
    as ``unavailable`` and never fails the gate — the evidence states what
    was actually checked.
    """
    root = Path(deliverable_root)
    if not root.is_dir():
        return {"status": "skipped", "reason": "deliverable root does not exist", "tools": {}}
    if not any(root.rglob("*.py")):
        return {"status": "skipped", "reason": "no python files", "tools": {}}
    gates: list[tuple[str, list[str], bool]]
    if tools is not None:
        enforced_by = {"ruff": True, "mypy": enforce_mypy}
        gates = [
            (name, _STATIC_TOOL_ARGS.get(name, ["."]), enforced_by.get(name, False))
            for name in tools
        ]
    else:
        gates = [("ruff", _STATIC_TOOL_ARGS["ruff"], True)]
        if run_mypy:
            gates.append(("mypy", _STATIC_TOOL_ARGS["mypy"], enforce_mypy))
    tool_records: dict[str, Any] = {}
    for name, args, enforced in gates:
        if importlib.util.find_spec(name) is None:
            tool_records[name] = {"status": "unavailable", "enforced": enforced}
            continue
        try:
            completed = subprocess.run(
                [python, "-m", name, *args],
                cwd=str(root),
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            tool_records[name] = {
                "status": "failed" if enforced else "recorded",
                "reason": f"{name} timed out after {timeout} seconds",
                "enforced": enforced,
            }
            continue
        output = (completed.stdout or b"").decode("utf-8", errors="replace")
        errors = (completed.stderr or b"").decode("utf-8", errors="replace")
        tail = output + ("\n[stderr]\n" + errors if errors.strip() else "")
        tool_records[name] = {
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "enforced": enforced,
            "output_tail": tail[-2000:],
        }
    enforced_failures = [
        name
        for name, record in tool_records.items()
        if record.get("status") == "failed" and record.get("enforced")
    ]
    return {
        "status": "failed" if enforced_failures else "passed",
        "tools": tool_records,
        "reason": None,
    }
