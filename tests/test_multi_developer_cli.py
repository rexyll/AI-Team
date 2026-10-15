from benchmarks.multi_developer.__main__ import main


def test_cli_runs_single_scenario(capsys):
    assert main(["--developers", "1", "--scenario", "fully-parallel", "--delay", "0"]) == 0
    output = capsys.readouterr().out
    assert "fully-parallel" in output
    assert "developers" in output
    assert "completed" in output


def test_cli_runs_multiple_developer_counts_and_baseline(capsys):
    assert main(
        [
            "--developers",
            "1",
            "2",
            "3",
            "--scenario",
            "fully-parallel",
            "--delay",
            "0",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "1" in output
    assert "2" in output
    assert "3" in output
    assert "Baseline comparison:" in output
    assert "speedup=" in output


def test_cli_repeat_reports_statistics(capsys):
    assert main(
        [
            "--developers",
            "1",
            "2",
            "--scenario",
            "fully-parallel",
            "--delay",
            "0",
            "--repeat",
            "3",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "runs" in output
    assert "mean_s" in output
    assert "median_s" in output
    assert "stddev_s" in output
    assert "Baseline comparison (mean duration):" in output
    assert "efficiency=" in output


def test_cli_rejects_invalid_developer_count():
    try:
        main(["--developers", "0"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("invalid developer count must be rejected")


def test_cli_rejects_invalid_repeat():
    try:
        main(["--repeat", "0"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("invalid repeat must be rejected")
