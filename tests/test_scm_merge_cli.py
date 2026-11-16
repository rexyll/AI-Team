from __future__ import annotations

from types import SimpleNamespace

import main


class _TTYOutput:
    def __init__(self, stream):
        self._stream = stream

    def write(self, value):
        return self._stream.write(value)

    def flush(self):
        return self._stream.flush()

    def isatty(self):
        return True


def _patch_tty_output(monkeypatch, *names):
    for name in names:
        stream = getattr(main.sys, name)
        monkeypatch.setattr(main.sys, name, _TTYOutput(stream))


def test_parser_accepts_merge_method_and_pr_number():
    args = main.build_parser().parse_args([
        "--scm-merge-pr", "18", "--scm-merge-method", "rebase"
    ])

    assert args.scm_merge_pr == 18
    assert args.scm_merge_method == "rebase"


def test_merge_cli_requires_ready_evidence_and_explicit_confirmation(monkeypatch, capsys):
    head = "a" * 40
    issued = []

    class FakeAuthority:
        def issue(self, **kwargs):
            issued.append(kwargs)
            return SimpleNamespace(**kwargs)

    class FakeService:
        def merge_pull_request(self, repository, number, *, approval, merge_method):
            assert repository == "acme/widget"
            assert number == 18
            assert approval.operation == "merge_pull_request"
            assert approval.target == f"18:{head}:main:squash"
            assert merge_method == "squash"
            return {"status": "merged", "sha": "b" * 40}

    runtime = SimpleNamespace(
        service=FakeService(),
        repository="acme/widget",
        approval_authority=FakeAuthority(),
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            assert config.repository == "acme/widget"

        def poll_pull_request(self, number):
            return {
                "status": "ready",
                "head_sha": head,
                "base_branch": "main",
                "ci_status": "success",
                "review_status": "approved",
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    _patch_tty_output(monkeypatch, "stderr")
    monkeypatch.setattr("builtins.input", lambda: "yes")
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-merge-pr", "18", "--output", "json"])

    assert main.main() == 0
    assert issued == [{
        "operation": "merge_pull_request",
        "repository": "acme/widget",
        "target": f"18:{head}:main:squash",
        "approved_by": "human:interactive-cli",
    }]
    assert '"status": "merged"' in capsys.readouterr().out


def test_merge_cli_does_not_prompt_or_issue_approval_when_ci_is_not_green(monkeypatch, capsys):
    class FakeAuthority:
        def issue(self, **kwargs):
            raise AssertionError("merge approval must not be issued for blocked PR")

    runtime = SimpleNamespace(
        service=SimpleNamespace(),
        repository="acme/widget",
        approval_authority=FakeAuthority(),
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            pass

        def poll_pull_request(self, number):
            return {
                "status": "ci_failed",
                "head_sha": "a" * 40,
                "base_branch": "main",
                "ci_status": "failure",
                "review_status": "approved",
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-merge-pr", "18"])

    assert main.main() == 2
    assert "Merge blocked" in capsys.readouterr().out


def test_merge_cli_cancellation_does_not_issue_approval(monkeypatch, capsys):
    class FakeAuthority:
        def issue(self, **kwargs):
            raise AssertionError("cancelled merge must not issue approval")

    runtime = SimpleNamespace(
        service=SimpleNamespace(),
        repository="acme/widget",
        approval_authority=FakeAuthority(),
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            pass

        def poll_pull_request(self, number):
            return {
                "status": "ready",
                "head_sha": "a" * 40,
                "base_branch": "main",
                "ci_status": "success",
                "review_status": "approved",
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    _patch_tty_output(monkeypatch, "stdout", "stderr")
    monkeypatch.setattr("builtins.input", lambda: "no")
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-merge-pr", "18"])

    assert main.main() == 3
    assert "cancelled" in capsys.readouterr().out.lower()


def test_merge_cli_refuses_when_preview_is_not_visible(monkeypatch, capsys):
    head = "a" * 40

    class FakeAuthority:
        def issue(self, **kwargs):
            raise AssertionError("merge approval must not be issued when preview is hidden")

    runtime = SimpleNamespace(
        service=SimpleNamespace(),
        repository="acme/widget",
        approval_authority=FakeAuthority(),
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            pass

        def poll_pull_request(self, number):
            return {
                "status": "ready",
                "head_sha": head,
                "base_branch": "main",
                "ci_status": "success",
                "review_status": "approved",
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    _patch_tty_output(monkeypatch, "stderr")
    monkeypatch.setattr("builtins.input", lambda: "yes")
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-merge-pr", "18"])
    assert main.main() == 1
    assert "visible terminal preview" in capsys.readouterr().err


def test_merge_cli_refuses_non_interactive_stdin(monkeypatch, capsys):
    class FakeAuthority:
        def issue(self, **kwargs):
            raise AssertionError("non-interactive merge must not issue approval")

    runtime = SimpleNamespace(
        service=SimpleNamespace(),
        repository="acme/widget",
        approval_authority=FakeAuthority(),
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            pass

        def poll_pull_request(self, number):
            return {
                "status": "ready",
                "head_sha": "a" * 40,
                "base_branch": "main",
                "ci_status": "success",
                "review_status": "approved",
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.stdin", type("Pipe", (), {"isatty": lambda self: False})())
    monkeypatch.setattr("sys.argv", ["ai-team", "--scm-merge-pr", "18"])

    assert main.main() == 1
    assert "interactive terminal" in capsys.readouterr().err
