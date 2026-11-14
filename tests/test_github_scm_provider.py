from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from runtime.github_scm_provider import (
    GitHubAPIError,
    GitHubRESTTransport,
    GitHubSCMProvider,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if not self.responses:
            raise AssertionError("unexpected GitHub API request")
        return self.responses.pop(0)


class FakeGitService:
    def __init__(self, remote="https://github.com/acme/widget.git", output="exit_code=0\n"):
        self.remote = remote
        self.output = output
        self.calls = []

    def remote_url(self, local_repository):
        self.calls.append(("remote_url", local_repository))
        return self.remote

    def head_commit(self, local_repository):
        self.calls.append(("head_commit", local_repository))
        return "e" * 40

    def push(self, local_repository, *, branch, commit_sha):
        self.calls.append(("push", local_repository, branch, commit_sha))
        return self.output


def test_push_branch_requires_matching_origin_and_uses_non_force_host_git():
    transport = FakeTransport([])
    git = FakeGitService()
    provider = GitHubSCMProvider(transport, git_service=git)

    result = provider.push_branch("acme/widget", "/workspace/widget", "feature/scm", expected_head_sha="e" * 40)

    assert result == {
        "status": "pushed",
        "repository": "acme/widget",
        "branch": "feature/scm",
    }
    assert git.calls == [
        ("remote_url", "/workspace/widget"),
        ("head_commit", "/workspace/widget"),
        ("push", "/workspace/widget", "feature/scm", "e" * 40),
    ]


def test_push_branch_rejects_origin_for_another_repository():
    git = FakeGitService(remote="https://github.com/acme/other.git")
    provider = GitHubSCMProvider(FakeTransport([]), git_service=git)

    with pytest.raises(PermissionError, match="does not match"):
        provider.push_branch("acme/widget", "/workspace/widget", "main", expected_head_sha="e" * 40)

    assert [call[0] for call in git.calls] == ["remote_url"]


def test_push_branch_reports_nonzero_git_exit_code():
    git = FakeGitService(output="exit_code=128\nfatal: rejected")
    provider = GitHubSCMProvider(FakeTransport([]), git_service=git)

    with pytest.raises(GitHubAPIError, match="git push failed"):
        provider.push_branch("acme/widget", "/workspace/widget", "main")


def test_create_pull_request_creates_when_no_open_match():
    transport = FakeTransport([
        [],
        {"number": 12, "html_url": "https://github.com/acme/widget/pull/12"},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.create_or_update_pull_request(
        "acme/widget", head="feature/a", base="main", title="Feature A", body="Body"
    )

    assert result == {
        "status": "created",
        "number": 12,
        "url": "https://github.com/acme/widget/pull/12",
        "head": "feature/a",
        "base": "main",
    }
    assert transport.calls[1][0] == "POST"
    assert transport.calls[1][2]["head"] == "feature/a"


def test_create_pull_request_updates_existing_open_match():
    transport = FakeTransport([
        [{"number": 12}],
        {"number": 12, "html_url": "https://github.com/acme/widget/pull/12"},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.create_or_update_pull_request(
        "acme/widget", head="feature/a", base="main", title="Updated", body="New body"
    )

    assert result["status"] == "updated"
    assert transport.calls[1][0] == "PATCH"
    assert transport.calls[1][2]["title"] == "Updated"


def test_ci_status_aggregates_checks_and_commit_statuses():
    transport = FakeTransport([
        {"check_runs": [
            {"name": "unit", "status": "completed", "conclusion": "success"},
            {"name": "security", "status": "completed", "conclusion": "success"},
        ]},
        {"state": "success", "statuses": [{"state": "success"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_ci_status("acme/widget", "a" * 40)

    assert result["status"] == "success"
    assert len(result["check_runs"]) == 2


def test_ci_status_is_pending_if_any_check_is_in_progress():
    transport = FakeTransport([
        {"check_runs": [{"name": "unit", "status": "in_progress", "conclusion": None}]},
        {"state": "pending", "statuses": [{"state": "pending"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_ci_status("acme/widget", "b" * 40)["status"] == "pending"


def test_ci_status_fails_if_any_check_fails():
    transport = FakeTransport([
        {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "failure"}]},
        {"state": "failure", "statuses": [{"state": "failure"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_ci_status("acme/widget", "c" * 40)["status"] == "failure"


def test_review_status_uses_latest_review_per_user():
    transport = FakeTransport([[
        {"user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "submitted_at": "2026-01-01T00:00:00Z"},
        {"user": {"login": "reviewer"}, "state": "APPROVED", "submitted_at": "2026-01-02T00:00:00Z"},
        {"user": {"login": "second"}, "state": "APPROVED", "submitted_at": "2026-01-01T00:00:00Z"},
    ]])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_review_status("acme/widget", 12)

    assert result["status"] == "approved"
    assert result["review_count"] == 2


def test_review_status_keeps_changes_requested_as_blocker():
    transport = FakeTransport([[
        {"user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "submitted_at": "2026-01-01T00:00:00Z"},
        {"user": {"login": "second"}, "state": "APPROVED", "submitted_at": "2026-01-02T00:00:00Z"},
    ]])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_review_status("acme/widget", 12)["status"] == "changes_requested"


def test_merge_pull_request_calls_github_merge_endpoint():
    transport = FakeTransport([{"merged": True, "sha": "d" * 40, "message": "merged"}])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.merge_pull_request("acme/widget", 12, merge_method="squash", expected_head_sha="d" * 40)

    assert result == {"status": "merged", "sha": "d" * 40, "message": "merged"}
    assert transport.calls[0][0] == "PUT"
    assert transport.calls[0][2]["sha"] == "d" * 40


def test_rest_transport_injects_host_token_without_returning_it():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    transport = GitHubRESTTransport("host-secret-token")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = transport.request("GET", "/repos/acme/widget")

    assert result == {"ok": True}
    assert captured["authorization"] == "Bearer host-secret-token"
    assert captured["url"] == "https://api.github.com/repos/acme/widget"


def test_rest_transport_sanitizes_http_error_without_echoing_token():
    class ErrorResponse:
        code = 403

        def read(self):
            return json.dumps({"message": "Resource not accessible"}).encode()

        def close(self):
            return None

    transport = GitHubRESTTransport("host-secret-token")
    with patch("urllib.request.urlopen", side_effect=__import__("urllib.error").error.HTTPError(
        "https://api.github.com/repos/acme/widget", 403, "Forbidden", {}, ErrorResponse()
    )):
        with pytest.raises(GitHubAPIError, match="HTTP 403") as error:
            transport.request("GET", "/repos/acme/widget")

    assert "host-secret-token" not in str(error.value)


def test_push_branch_rejects_local_head_drift_after_approval():
    class DriftingGitService(FakeGitService):
        def __init__(self):
            super().__init__()
            self.heads = iter(["e" * 40, "f" * 40])

        def head_commit(self, local_repository):
            self.calls.append(("head_commit", local_repository))
            return next(self.heads)

    git = DriftingGitService()
    provider = GitHubSCMProvider(FakeTransport([]), git_service=git)

    with pytest.raises(PermissionError, match="HEAD changed"):
        provider.push_branch(
            "acme/widget",
            "/workspace/widget",
            "release/1.2",
            expected_head_sha="e" * 40,
        )

    assert not any(call[0] == "push" for call in git.calls)


def test_rest_transport_rejects_untrusted_api_hosts_and_paths():
    with pytest.raises(ValueError, match="api.github.com"):
        GitHubRESTTransport("host-secret-token", api_base="https://attacker.example")
    transport = GitHubRESTTransport("host-secret-token")
    for path in ("/repos/../secrets", "//attacker.example/repos/acme/widget", "/repos/acme/widget\\\\.."):
        with pytest.raises(ValueError, match="repository-scoped"):
            transport.request("GET", path)
