from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def evaluate_coverage(
    report: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    files = report.get("files")
    modules = policy.get("modules")
    if not isinstance(files, dict) or not isinstance(modules, dict) or not modules:
        return [], ["coverage report or module policy is missing/invalid"]

    totals: dict[str, dict[str, int]] = {}
    for path, row in files.items():
        module = Path(path).parts[0]
        summary = row.get("summary", {}) if isinstance(row, dict) else {}
        if not isinstance(summary, dict):
            continue
        bucket = totals.setdefault(
            module,
            {
                "statements": 0,
                "covered_lines": 0,
                "branches": 0,
                "covered_branches": 0,
            },
        )
        bucket["statements"] += int(summary.get("num_statements", 0))
        bucket["covered_lines"] += int(summary.get("covered_lines", 0))
        bucket["branches"] += int(summary.get("num_branches", 0))
        bucket["covered_branches"] += int(summary.get("covered_branches", 0))

    expected = set(modules)
    measured = {name for name, values in totals.items() if values["statements"] > 0}
    problems: list[str] = []
    if measured != expected:
        missing = sorted(expected - measured)
        unexpected = sorted(measured - expected)
        if missing:
            problems.append(f"coverage missing configured modules: {', '.join(missing)}")
        if unexpected:
            problems.append(f"coverage contains unconfigured modules: {', '.join(unexpected)}")

    results: list[dict[str, Any]] = []
    for module in sorted(expected & measured):
        actual = totals[module]
        threshold = modules[module]
        statements = actual["statements"]
        branches = actual["branches"]
        line_percent = 100.0 * actual["covered_lines"] / statements
        branch_percent = 100.0 * actual["covered_branches"] / branches if branches else 100.0
        line_floor = float(threshold["line_percent"])
        branch_floor = float(threshold["branch_percent"])
        results.append(
            {
                "module": module,
                "statements": statements,
                "branches": branches,
                "line_percent": line_percent,
                "branch_percent": branch_percent,
                "line_floor": line_floor,
                "branch_floor": branch_floor,
            }
        )
        if line_percent < line_floor:
            problems.append(
                f"{module} line coverage {line_percent:.2f}% is below {line_floor:.2f}%"
            )
        if branch_percent < branch_floor:
            problems.append(
                f"{module} branch coverage {branch_percent:.2f}% is below {branch_floor:.2f}%"
            )
    return results, problems


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: check_coverage_thresholds.py COVERAGE_JSON POLICY_JSON", file=sys.stderr)
        return 2
    report_path, policy_path = map(Path, args)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        results, problems = evaluate_coverage(report, policy)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"coverage gate could not evaluate its inputs: {exc}", file=sys.stderr)
        return 2

    print("Module coverage gate (Python 3.14)")
    for item in results:
        print(
            f"{item['module']}: line {item['line_percent']:.2f}% "
            f"(min {item['line_floor']:.2f}%), branch {item['branch_percent']:.2f}% "
            f"(min {item['branch_floor']:.2f}%)"
        )
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print("PASS: all configured module coverage floors satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
