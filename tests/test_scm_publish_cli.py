from __future__ import annotations

from types import SimpleNamespace

import main
from runtime.scm_provider import (
    SCMApprovalAuthority,
    SCMService,
    scm_pull_request_approval_target,
)


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


def test_parser_accepts_publish_options():
    args = main.build_parser().parse_args([
        "--scm-publish-pr",
        "--scm-local-repository", "/workspace/widget",
        "--scm-head-branch", "feature/widget",
        "--scm-base-branch", "main",
        "--scm-pr-title", "Add widget",
        "--scm-pr-body-file", "/tmp/pr-body.md",
    ])

    assert args.scm_publish_pr is True
    assert args.scm_head_branch == "feature/widget"


def test_publish_cli_requires_two_distinct_confirmations(monkeypatch, tmp_path, capsys):
    body_file = tmp_path / "body.md"
    body_file.write_text("Implementation details", encoding="utf-8")
    head_sha = "a" * 40
    issued = []

    class FakeAuthority:
        def issue(self, **kwargs):
            issued.append(kwargs)
            return SimpleNamespace(**kwargs)

    runtime = SimpleNamespace(
        service=SimpleNamespace(get_local_head_sha=lambda path: head_sha),
        repository="acme/widget",
        approval_authority=FakeAuthority(),
    )

    class FakeCoordinator:
        def __init__(self, service, config):
            assert config.repository == "acme/widget"
            assert config.base_branch == "main"

        def publish_and_open_pull_request(self, **kwargs):
            assert kwargs["push_approval"].operation == "push_branch"
            assert kwargs["pull_request_approval"].operation == "create_or_update_pull_request"
            return {
                "status": "published",
                "repository": "acme/widget",
                "head_branch": "feature/widget",
                "pull_request": {"number": 31, "status": "created"},
            }

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(
        main,
        "create_github_scm_runtime",
        lambda **kwargs: runtime,
    )
    monkeypatch.setattr(main, "SCMLifecycleCoordinator", FakeCoordinator)
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    _patch_tty_output(monkeypatch, "stdout", "stderr")
    monkeypatch.setattr("builtins.input", lambda: "yes")
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-team", "--scm-publish-pr",
            "--scm-local-repository", "/workspace/widget",
            "--scm-head-branch", "feature/widget",
            "--scm-pr-title", "Add widget",
            "--scm-pr-body-file", str(body_file),
        ],
    )

    assert main.main() == 0
    assert [item["operation"] for item in issued] == [
        "push_branch", "create_or_update_pull_request"
    ]
    assert issued[0]["target"] == f"feature/widget:{head_sha}"
    expected_pr_target = scm_pull_request_approval_target(
        head="feature/widget",
        base="main",
        title="Add widget",
        body="Implementation details",
        expected_head_sha=head_sha,
    )
    assert issued[1]["target"] == expected_pr_target
    output = capsys.readouterr().out
    assert "PR #31" in output
    assert "PR source SHA:" in output
    assert "PR approval SHA-256 (source SHA + title + body):" in output
    assert 'PR body (JSON-escaped): "Implementation details"' in output


def test_publish_cli_stops_if_first_confirmation_is_not_yes(monkeypatch, tmp_path, capsys):
    body_file = tmp_path / "body.md"
    body_file.write_text("Implementation details", encoding="utf-8")
    runtime = SimpleNamespace(
        service=SCMService(
            SimpleNamespace(get_local_head_sha=lambda path: "a" * 40),
            SCMApprovalAuthority(),
        ),
        repository="acme/widget",
        approval_authority=SimpleNamespace(issue=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("approval must not be issued after cancellation")
        )),
    )

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    _patch_tty_output(monkeypatch, "stdout", "stderr")
    monkeypatch.setattr("builtins.input", lambda: "no")
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-team", "--scm-publish-pr",
            "--scm-local-repository", "/workspace/widget",
            "--scm-head-branch", "feature/widget",
            "--scm-pr-title", "Add widget",
            "--scm-pr-body-file", str(body_file),
        ],
    )

    assert main.main() == 3
    assert "cancelled" in capsys.readouterr().out.lower()


def test_publish_cli_rejects_combination_with_delivery(monkeypatch):
    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        ["ai-team", "build a website", "--scm-publish-pr"],
    )

    try:
        main.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("publish command must be standalone")


def test_publish_cli_refuses_when_preview_is_not_visible(monkeypatch, tmp_path, capsys):
    body_file = tmp_path / "body.md"
    body_file.write_text("Implementation details", encoding="utf-8")
    runtime = SimpleNamespace(
        service=SCMService(
            SimpleNamespace(get_local_head_sha=lambda path: "a" * 40),
            SCMApprovalAuthority(),
        ),
        repository="acme/widget",
        approval_authority=SimpleNamespace(issue=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("approval must not be issued when preview is hidden")
        )),
    )
    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr("sys.stdin", type("TTY", (), {"isatty": lambda self: True})())
    _patch_tty_output(monkeypatch, "stderr")
    monkeypatch.setattr("builtins.input", lambda: "yes")
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-team", "--scm-publish-pr",
            "--scm-local-repository", "/workspace/widget",
            "--scm-head-branch", "feature/widget",
            "--scm-pr-title", "Add widget",
            "--scm-pr-body-file", str(body_file),
        ],
    )
    assert main.main() == 1
    assert "visible terminal preview" in capsys.readouterr().err


def test_publish_cli_refuses_non_interactive_stdin(monkeypatch, tmp_path, capsys):
    body_file = tmp_path / "body.md"
    body_file.write_text("Implementation details", encoding="utf-8")
    runtime = SimpleNamespace(
        service=SCMService(
            SimpleNamespace(get_local_head_sha=lambda path: "a" * 40),
            SCMApprovalAuthority(),
        ),
        repository="acme/widget",
        approval_authority=SimpleNamespace(issue=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("approval must not be issued without a terminal")
        )),
    )

    monkeypatch.setattr(main, "_ensure_log_safe_streams", lambda: None)
    monkeypatch.setattr(main, "create_github_scm_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr("sys.stdin", type("Pipe", (), {"isatty": lambda self: False})())
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-team", "--scm-publish-pr",
            "--scm-local-repository", "/workspace/widget",
            "--scm-head-branch", "feature/widget",
            "--scm-pr-title", "Add widget",
            "--scm-pr-body-file", str(body_file),
        ],
    )

    assert main.main() == 1
    assert "interactive terminal" in capsys.readouterr().err
