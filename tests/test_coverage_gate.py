import json
from pathlib import Path

from tools.check_coverage_thresholds import evaluate_coverage


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "coverage_thresholds.json").read_text(encoding="utf-8"))


def _report(*, agents_line: tuple[int, int] = (90, 100), extra_module: bool = False):
    files = {}
    for module in POLICY["modules"]:
        covered, statements = agents_line if module == "agents" else (90, 100)
        files[f"{module}/sample.py"] = {
            "summary": {
                "num_statements": statements,
                "covered_lines": covered,
                "num_branches": 20,
                "covered_branches": 18,
            }
        }
    if extra_module:
        files["unconfigured/sample.py"] = {
            "summary": {
                "num_statements": 1,
                "covered_lines": 1,
                "num_branches": 0,
                "covered_branches": 0,
            }
        }
    return {"files": files}


def test_risk_based_module_coverage_floors_accept_meeting_report():
    results, problems = evaluate_coverage(_report(), POLICY)

    assert len(results) == len(POLICY["modules"])
    assert problems == []
    assert {item["module"] for item in results} == set(POLICY["modules"])


def test_coverage_gate_rejects_module_below_line_floor():
    results, problems = evaluate_coverage(_report(agents_line=(79, 100)), POLICY)

    assert results
    assert any("agents line coverage" in problem for problem in problems)


def test_coverage_gate_rejects_unconfigured_or_missing_modules():
    report = _report(extra_module=True)
    del report["files"]["tools/sample.py"]

    results, problems = evaluate_coverage(report, POLICY)

    assert results
    assert any("missing configured modules: tools" in problem for problem in problems)
    assert any("unconfigured modules: unconfigured" in problem for problem in problems)


def test_coverage_gate_handles_modules_without_branchable_lines():
    report = _report()
    for row in report["files"].values():
        row["summary"]["num_branches"] = 0
        row["summary"]["covered_branches"] = 0

    results, problems = evaluate_coverage(report, POLICY)

    assert len(results) == len(POLICY["modules"])
    assert problems == []
    assert all(item["branch_percent"] == 100.0 for item in results)
