import pytest

from benchmarks.multi_developer.report import BenchmarkReport
from benchmarks.multi_developer.runner import BenchmarkResult


def _result(scenario: str, developers: int, duration: float) -> BenchmarkResult:
    return BenchmarkResult(
        scenario=scenario,
        developer_count=developers,
        task_count=4,
        completed=4,
        failed=0,
        blocked=0,
        duration_seconds=duration,
    )


def test_report_filters_and_renders_stable_rows():
    report = BenchmarkReport.from_results([
        _result("parallel", 1, 4.0),
        _result("parallel", 2, 2.0),
        _result("serial", 1, 3.0),
    ])

    parallel = report.for_scenario("parallel")
    assert len(parallel.results) == 2
    rendered = parallel.render_table()
    assert "scenario" in rendered
    assert "parallel" in rendered
    assert "2.000000" in rendered


def test_report_calculates_speedup_and_efficiency_against_per_scenario_baseline():
    report = BenchmarkReport.from_results([
        _result("parallel", 1, 4.0),
        _result("parallel", 2, 2.0),
        _result("parallel", 4, 1.5),
        _result("serial", 1, 3.0),
        _result("serial", 2, 3.2),
    ])

    measured = report.with_baseline()

    assert [(item.result.scenario, item.result.developer_count) for item in measured] == [
        ("parallel", 2),
        ("parallel", 4),
        ("serial", 2),
    ]
    assert measured[0].speedup == pytest.approx(2.0)
    assert measured[0].parallel_efficiency == pytest.approx(1.0)
    assert measured[1].speedup == pytest.approx(4.0 / 1.5)
    assert measured[1].parallel_efficiency == pytest.approx((4.0 / 1.5) / 4)


def test_report_rejects_invalid_baseline_count():
    report = BenchmarkReport.from_results([])
    for value in (0, -1):
        with pytest.raises(ValueError):
            report.with_baseline(value)
