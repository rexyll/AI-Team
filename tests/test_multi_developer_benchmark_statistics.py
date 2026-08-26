import pytest

from benchmarks.multi_developer.statistics import BenchmarkStatistics


def test_statistics_calculates_descriptive_metrics():
    stats = BenchmarkStatistics.from_durations("parallel", 2, [1.0, 2.0, 3.0])

    assert stats.runs == 3
    assert stats.mean_seconds == pytest.approx(2.0)
    assert stats.median_seconds == pytest.approx(2.0)
    assert stats.min_seconds == pytest.approx(1.0)
    assert stats.max_seconds == pytest.approx(3.0)
    assert stats.stddev_seconds == pytest.approx(1.0)
    assert stats.coefficient_of_variation == pytest.approx(0.5)


def test_statistics_speedup_and_efficiency_use_mean_duration():
    baseline = BenchmarkStatistics.from_durations("parallel", 1, [4.0, 4.0])
    measured = BenchmarkStatistics.from_durations("parallel", 2, [2.0, 2.0])

    assert measured.speedup_against(baseline) == pytest.approx(2.0)
    assert measured.efficiency_against(baseline) == pytest.approx(1.0)


def test_statistics_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        BenchmarkStatistics.from_durations("parallel", 1, [])
    with pytest.raises(ValueError):
        BenchmarkStatistics.from_durations("parallel", 1, [0.1, -0.1])
    with pytest.raises(ValueError):
        BenchmarkStatistics.from_durations("parallel", 0, [0.1])
    with pytest.raises(ValueError):
        BenchmarkStatistics.from_durations("", 1, [0.1])


def test_statistics_rejects_mismatched_baseline_scenario():
    baseline = BenchmarkStatistics.from_durations("serial", 1, [1.0])
    measured = BenchmarkStatistics.from_durations("parallel", 2, [0.5])

    with pytest.raises(ValueError):
        measured.speedup_against(baseline)
