from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import scm_live_readonly_smoke as smoke


class FakeService:
    def __init__(self, *, ci_status="pending", review_status="pending", draft=False):
        self.ci_status = ci_status
        self.review_status = review_status
        self.draft = draft
        self.calls = []

    def get_pull_request(self, repository, pull_request_number):
        self.calls.append(("pull_request", repository, pull_request_number))
        return {
            "state": "open",
            "merged": False,
            "draft": self.draft,
            "head_sha": "a" * 40,
            "base_branch": "main",
        }

    def get_ci_status(self, repository, commit_sha):
        self.calls.append(("ci", repository, commit_sha))
        return {
            "status": self.ci_status,
            "commit_status": "pending",
            "check_runs": [
                {
                    "name": "unit tests",
                    "status": "in_progress",
                    "conclusion": None,
                    "output": {"summary": "ghp-secret-must-not-appear"},
                }
            ],
        }

    def get_review_status(self, repository, pull_request_number):
        self.calls.append(("reviews", repository, pull_request_number))
        return {
            "status": self.review_status,
            "review_count": 0,
            "states": [],
        }


def test_readonly_probe_reports_blocked_evidence_without_echoing_remote_output(
    monkeypatch, capsys
):
    service = FakeService()
    runtime = SimpleNamespace(
        service=service,
        repository="acme/widget",
        pull_request_number=42,
    )
    monkeypatch.setattr(smoke, "create_github_scm_runtime", lambda: runtime)

    assert smoke.main() == 0
    output = capsys.readouterr().out
    result = json.loads(output)

    assert result["ok"] is True
    assert result["assessment"] == "blocked"
    assert result["blockers"] == ["ci_not_success", "review_not_approved"]
    assert result["ci"]["check_runs"] == [
        {
            "name": "unit tests",
            "status": "in_progress",
        }
    ]
    assert "ghp-secret-must-not-appear" not in output
    assert [call[0] for call in service.calls] == [
        "pull_request",
        "ci",
        "reviews",
    ]


def test_readonly_probe_reports_ready_only_for_open_green_approved_pr():
    service = FakeService(ci_status="success", review_status="approved")

    result = smoke.observe(service, "acme/widget", 42)

    assert result["assessment"] == "ready"
    assert result["blockers"] == []
    assert result["pull_request"]["head_sha"] == "a" * 40
    assert result["pull_request"]["base_branch"] == "main"


def test_readonly_probe_blocks_draft_pr_even_when_ci_and_review_are_green():
    service = FakeService(ci_status="success", review_status="approved", draft=True)

    result = smoke.observe(service, "acme/widget", 42)

    assert result["assessment"] == "blocked"
    assert result["blockers"] == ["pull_request_draft"]
    assert result["pull_request"]["draft"] is True


def test_readonly_probe_does_not_print_exception_message_or_secret(
    monkeypatch, capsys
):
    class BrokenService:
        def get_pull_request(self, repository, pull_request_number):
            raise RuntimeError("ghp-secret-must-not-appear")

    runtime = SimpleNamespace(
        service=BrokenService(),
        repository="acme/widget",
        pull_request_number=42,
    )
    monkeypatch.setattr(smoke, "create_github_scm_runtime", lambda: runtime)

    assert smoke.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error_type"] == "RuntimeError"
    assert "ghp-secret-must-not-appear" not in output


def test_live_smoke_workflow_uses_read_only_repository_permissions():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scm-live-readonly-smoke.yml"
    content = path.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in content
    assert "secrets.GITHUB_TOKEN" in content
    assert "pull-requests: read" in content
    assert "checks: read" in content
    assert "statuses: read" in content
    assert "contents: read" in content
    assert "contents: write" not in content
    assert "pull-requests: write" not in content
    assert "checks: write" not in content
    assert "statuses: write" not in content
