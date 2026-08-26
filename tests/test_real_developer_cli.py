from __future__ import annotations

import pytest

from benchmarks.real_developer.cli import build_parser, main


def test_real_developer_cli_exposes_live_guarded_options():
    args = build_parser().parse_args(
        ["--developers", "1", "2", "--scenario", "independent", "--repeat", "3", "--provider", "agnes", "--model", "agnes-2.5-flash", "--live"]
    )
    assert args.developers == [1, 2]
    assert args.scenario == "independent"
    assert args.repeat == 3
    assert args.provider == "agnes"
    assert args.model == "agnes-2.5-flash"
    assert args.live is True


def test_real_developer_cli_rejects_live_execution_without_explicit_flag():
    with pytest.raises(SystemExit, match="requires explicit --live"):
        main(["--developers", "1"])


def test_real_developer_cli_rejects_unknown_scenario():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--scenario", "unknown"])


def test_real_developer_cli_validates_developer_count():
    with pytest.raises(SystemExit, match="greater than 0"):
        main(["--developers", "0", "--live"])


def test_real_developer_cli_validates_repeat():
    with pytest.raises(SystemExit, match="greater than 0"):
        main(["--repeat", "0", "--live"])
