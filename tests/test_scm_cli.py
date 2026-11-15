from __future__ import annotations

import json
from types import SimpleNamespace

import main


def test_parser_accepts_read_only_scm_poll_number():
    args = main.build_parser().parse_args(["--scm-poll-pr", "42", "--output", "json"])

    assert args.requirement is None
    assert args.scm_poll_pr == 42
    assert args.output == "json"


def test_scm_poll_cli_emits_json_and_returns_success_for_ready(monkeypatch, capsys):
    observation = {
        "status": "ready",
        "repository": "acme/widget",
        "pull_request_number": 42,
        "head_sha": "a" * 40,
        "ci_status": "success",
        "review_status": "approved",
        "attempt": 1,
        "max_attempts": 12,
    }
    runtime = SimpleNamespace(
        service=object(),
        repository="acme/widget",
        pull_request_number=42,
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            assert service is runtime.service
            assert config.repository == "acme/widget"

        def poll_pull_request(self, number):
            assert number == 42
            return observation

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-poll-pr", "42", "--output", "json"])

    assert main.main() == 0
    assert json.loads(capsys.readouterr().out) == observation


def test_scm_poll_cli_returns_nonzero_for_blocked_evidence(monkeypatch, capsys):
    runtime = SimpleNamespace(
        service=object(),
        repository="acme/widget",
        pull_request_number=42,
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            pass

        def poll_pull_request(self, number):
            return {
                "status": "ci_failed",
                "pull_request_number": number,
                "head_sha": "b" * 40,
                "ci_status": "failure",
                "review_status": "approved",
                "attempt": 1,
                "max_attempts": 12,
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-poll-pr", "42"])

    assert main.main() == 2
    assert "[SCM] PR #42 ci_failed" in capsys.readouterr().out


def test_scm_poll_cli_rejects_combination_with_delivery_request(monkeypatch):
    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        ["ai-team", "build a website", "--scm-poll-pr", "42"],
    )

    try:
        main.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("conflicting delivery request should be rejected")
