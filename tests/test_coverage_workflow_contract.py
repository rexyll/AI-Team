from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"


def test_coverage_tool_is_a_locked_development_dependency():
    requirements = DEV_REQUIREMENTS.read_text(encoding="utf-8-sig")
    linux_lock = (ROOT / "requirements-dev-linux-py314.lock").read_text(encoding="utf-8-sig")
    windows_lock = (ROOT / "requirements-dev-windows-py314.lock").read_text(encoding="utf-8-sig")

    assert "coverage>=7.10,<8" in requirements
    assert "coverage==" in linux_lock
    assert "coverage==" in windows_lock
    assert "--hash=sha256:" in linux_lock
    assert "--hash=sha256:" in windows_lock


def test_ci_collects_line_and_branch_coverage_without_machine_timing_tests():
    workflow = CI.read_text(encoding="utf-8-sig")

    assert "coverage-baseline:" in workflow
    assert "coverage run --branch --source=" in workflow
    assert "coverage json --pretty-print -o coverage.json" in workflow
    assert "coverage html -d coverage-html" in workflow
    assert "coverage report -m" in workflow
    assert "python tools/check_coverage_thresholds.py coverage.json config/coverage_thresholds.json" in workflow
    assert "config/coverage_thresholds.json" in workflow
    assert "coverage-baseline-python314" in workflow
    assert "retention-days: 30" in workflow

    # Timing-sensitive checks remain in the ordinary full regression job;
    # only the separately instrumented coverage measurement excludes them.
    for test_file in (
        "tests/test_large_project_benchmark.py",
        "tests/test_multi_developer_benchmark.py",
        "tests/test_real_developer_ab_benchmark.py",
        "tests/test_real_developer_benchmark_parallelism.py",
        "tests/test_workflow_event_performance_contract.py",
        "tests/test_workflow_event_performance_regression_contract.py",
    ):
        assert f"--ignore={test_file}" in workflow
    assert "python -m pytest -q" in workflow
