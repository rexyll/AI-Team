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
        provider.push_branch("acme/widget", "/workspace/widget", "main", expected_head_sha="e" * 40)


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


@pytest.mark.parametrize(
    "lookup_response",
    [
        None,
        {},
        "unexpected response",
        [None],
        [{"number": True}],
        [{"number": 0}],
        [{"number": 12}, {"number": 13}],
    ],
)
def test_create_pull_request_fails_closed_on_invalid_or_ambiguous_lookup(
    lookup_response,
):
    transport = FakeTransport([lookup_response])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match="invalid|multiple"):
        provider.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title="Feature A",
            body="Body",
        )

    assert [call[0] for call in transport.calls] == ["GET"]


def test_create_pull_request_rejects_invalid_write_response_number():
    transport = FakeTransport([[], {"number": True}])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match="invalid pull request response"):
        provider.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title="Feature A",
            body="Body",
        )

    assert [call[0] for call in transport.calls] == ["GET", "POST"]


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


def test_get_pull_request_includes_draft_state_and_requires_complete_metadata():
    transport = FakeTransport([{
        "head": {"sha": "a" * 40},
        "base": {"ref": "main"},
        "user": {"login": "pr-author"},
        "state": "open",
        "merged": False,
        "draft": False,
    }])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_pull_request("acme/widget", 12) == {
        "head_sha": "a" * 40,
        "state": "open",
        "merged": False,
        "draft": False,
        "base_branch": "main",
        "author_login": "pr-author",
    }

    incomplete = FakeTransport([{
        "head": {"sha": "a" * 40},
        "base": {"ref": "main"},
        "user": {"login": "pr-author"},
        "state": "open",
        "merged": False,
    }])
    with pytest.raises(GitHubAPIError, match="incomplete pull request state"):
        GitHubSCMProvider(incomplete, git_service=FakeGitService()).get_pull_request("acme/widget", 12)

    missing_author = FakeTransport([{
        "head": {"sha": "a" * 40},
        "base": {"ref": "main"},
        "state": "open",
        "merged": False,
        "draft": False,
    }])
    with pytest.raises(GitHubAPIError, match="incomplete pull request state"):
        GitHubSCMProvider(missing_author, git_service=FakeGitService()).get_pull_request("acme/widget", 12)


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


def test_ci_status_paginates_check_runs_before_reporting_failure_or_success():
    first_page = [
        {"name": f"check-{index}", "status": "completed", "conclusion": "success"}
        for index in range(100)
    ]
    second_page = [
        {"name": "late-failure", "status": "completed", "conclusion": "failure"}
    ]
    transport = FakeTransport([
        {"check_runs": first_page},
        {"check_runs": second_page},
        {"state": "success", "statuses": [{"state": "success"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_ci_status("acme/widget", "b" * 40)

    assert result["status"] == "failure"
    assert result["checks_complete"] is True
    assert transport.calls[0][1].endswith("?per_page=100&page=1")
    assert transport.calls[1][1].endswith("?per_page=100&page=2")


@pytest.mark.parametrize(
    "conclusion",
    ["action_required", "cancelled", "failure", "stale", "startup_failure", "timed_out"],
)
def test_ci_status_treats_terminal_non_success_conclusions_as_failure(conclusion):
    transport = FakeTransport([
        {"check_runs": [{
            "name": "terminal-check",
            "status": "completed",
            "conclusion": conclusion,
        }]},
        {"state": "success", "statuses": [{"state": "success"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_ci_status("acme/widget", "d" * 40)["status"] == "failure"


def test_ci_status_returns_unknown_for_an_unrecognized_completed_conclusion():
    transport = FakeTransport([
        {"check_runs": [{
            "name": "future-check",
            "status": "completed",
            "conclusion": "future_conclusion",
        }]},
        {"state": "success", "statuses": [{"state": "success"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_ci_status("acme/widget", "e" * 40)["status"] == "unknown"


@pytest.mark.parametrize(
    "bad_response",
    [
        {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "success"}, "malformed"]},
        {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "success"}]},
    ],
)
def test_ci_status_rejects_malformed_check_or_status_entries(bad_response):
    if "statuses" not in bad_response:
        responses = [
            bad_response,
            {"state": "success", "statuses": [{"state": "success"}, "malformed"]},
        ]
    else:
        responses = [bad_response, {"state": "success", "statuses": [{"state": "success"}]}]
    transport = FakeTransport(responses)
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match="invalid"):
        provider.get_ci_status("acme/widget", "f" * 40)


def test_ci_status_uses_successful_check_runs_when_no_legacy_statuses_exist():
    transport = FakeTransport([
        {"check_runs": [
            {"name": "unit", "status": "completed", "conclusion": "success"},
            {"name": "security", "status": "completed", "conclusion": "success"},
        ]},
        {"state": "pending", "statuses": []},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_ci_status("acme/widget", "1" * 40)

    assert result["status"] == "success"
    assert result["commit_status"] == "pending"
    assert result["check_runs"] and result["checks_complete"] is True


def test_ci_status_stays_pending_when_neither_check_runs_nor_statuses_exist():
    transport = FakeTransport([
        {"check_runs": []},
        {"state": "pending", "statuses": []},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_ci_status("acme/widget", "2" * 40)

    assert result["status"] == "pending"


def test_ci_status_does_not_ignore_pending_legacy_contexts_when_checks_pass():
    transport = FakeTransport([
        {"check_runs": [{
            "name": "unit",
            "status": "completed",
            "conclusion": "success",
        }]},
        {"state": "pending", "statuses": [{"state": "pending"}]},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_ci_status("acme/widget", "3" * 40)["status"] == "pending"


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


def _review_pr_metadata(head_sha="a" * 40, author="pr-author"):
    return {
        "head": {"sha": head_sha},
        "base": {"ref": "main"},
        "user": {"login": author},
        "state": "open",
        "merged": False,
        "draft": False,
    }


def _review(login, state, submitted_at, commit_id="a" * 40):
    return {
        "user": {"login": login},
        "state": state,
        "submitted_at": submitted_at,
        "commit_id": commit_id,
    }


def test_review_status_uses_latest_non_author_review_on_current_head():
    transport = FakeTransport([[
        _review("reviewer", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z"),
        _review("reviewer", "APPROVED", "2026-01-02T00:00:00Z"),
        _review("second", "APPROVED", "2026-01-01T00:00:00Z"),
    ], _review_pr_metadata()])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_review_status("acme/widget", 12)

    assert result["status"] == "approved"
    assert result["review_count"] == 2
    assert result["reviewed_head_sha"] == "a" * 40
    assert transport.calls[-1][1].endswith("/pulls/12")


def test_review_status_ignores_approval_from_pr_author():
    transport = FakeTransport([[
        _review("pr-author", "APPROVED", "2026-01-02T00:00:00Z"),
    ], _review_pr_metadata(author="pr-author")])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_review_status("acme/widget", 12)

    assert result["status"] == "pending"
    assert result["review_count"] == 0


def test_review_status_ignores_stale_approval_from_previous_head():
    transport = FakeTransport([[
        _review("reviewer", "APPROVED", "2026-01-02T00:00:00Z", commit_id="b" * 40),
    ], _review_pr_metadata(head_sha="a" * 40)])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_review_status("acme/widget", 12)

    assert result["status"] == "pending"
    assert result["review_count"] == 0
    assert result["reviewed_head_sha"] == "a" * 40


def test_review_status_reads_later_pages_before_assessing_latest_review_per_user():
    first_page = [
        _review(f"reviewer-{index}", "COMMENTED", "2026-01-01T00:00:00Z")
        for index in range(99)
    ]
    first_page.append(
        _review("reviewer-latest", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z")
    )
    second_page = [
        _review("reviewer-latest", "APPROVED", "2026-01-02T00:00:00Z")
    ]
    transport = FakeTransport([first_page, second_page, _review_pr_metadata()])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_review_status("acme/widget", 12)

    assert result["status"] == "approved"
    assert result["reviews_complete"] is True
    assert transport.calls[0][1].endswith("?per_page=100&page=1")
    assert transport.calls[1][1].endswith("?per_page=100&page=2")
    assert transport.calls[2][1].endswith("/pulls/12")


@pytest.mark.parametrize(
    "reviews",
    [
        [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z"), "malformed"],
        [{"user": None, "state": "APPROVED", "submitted_at": "2026-01-01T00:00:00Z", "commit_id": "a" * 40}],
        [{"user": {"login": "reviewer"}, "submitted_at": "2026-01-01T00:00:00Z", "commit_id": "a" * 40}],
        [{"user": {"login": "reviewer"}, "state": "APPROVED", "submitted_at": "2026-01-01T00:00:00Z"}],
        [{"user": {"login": "reviewer"}, "state": "APPROVED", "submitted_at": "2026-01-01T00:00:00Z", "commit_id": "not-a-sha"}],
    ],
)
def test_review_status_rejects_malformed_review_evidence(reviews):
    transport = FakeTransport([reviews])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match="invalid|incomplete"):
        provider.get_review_status("acme/widget", 12)


def test_review_status_fails_closed_on_unknown_review_state_even_with_current_head_approval():
    transport = FakeTransport([[
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z"),
        _review("future-reviewer", "FUTURE_STATE", "2026-01-02T00:00:00Z"),
    ], _review_pr_metadata()])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.get_review_status("acme/widget", 12)

    assert result["status"] == "pending"


def test_review_status_keeps_current_head_changes_requested_as_blocker():
    transport = FakeTransport([[
        _review("reviewer", "CHANGES_REQUESTED", "2026-01-01T00:00:00Z"),
        _review("second", "APPROVED", "2026-01-02T00:00:00Z"),
    ], _review_pr_metadata()])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    assert provider.get_review_status("acme/widget", 12)["status"] == "changes_requested"


def test_merge_pull_request_rechecks_head_and_base_before_github_merge_endpoint():
    transport = FakeTransport([
        {
            "head": {"sha": "d" * 40},
            "base": {"ref": "main"},
            "state": "open",
            "merged": False,
            "draft": False,
        },
        {"merged": True, "sha": "e" * 40, "message": "merged"},
    ])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    result = provider.merge_pull_request(
        "acme/widget",
        12,
        merge_method="squash",
        expected_head_sha="d" * 40,
        expected_base_branch="main",
    )

    assert result == {"status": "merged", "sha": "e" * 40, "message": "merged"}
    assert [call[0] for call in transport.calls] == ["GET", "PUT"]
    assert transport.calls[1][2]["sha"] == "d" * 40


def test_merge_pull_request_rejects_malformed_fresh_pr_metadata():
    transport = FakeTransport([None])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match="invalid pull request metadata"):
        provider.merge_pull_request(
            "acme/widget",
            12,
            merge_method="squash",
            expected_head_sha="d" * 40,
            expected_base_branch="main",
        )

    assert [call[0] for call in transport.calls] == ["GET"]


@pytest.mark.parametrize(
    ("field_updates", "reason"),
    [
        ({"head": {"sha": "f" * 40}}, "head or base changed"),
        ({"state": "closed"}, "head or base changed"),
        ({"merged": True}, "head or base changed"),
        ({"draft": True}, "head or base changed"),
    ],
)
def test_merge_pull_request_rejects_state_or_head_drift_before_put(field_updates, reason):
    current = {
        "head": {"sha": "d" * 40},
        "base": {"ref": "main"},
        "state": "open",
        "merged": False,
        "draft": False,
    }
    current.update(field_updates)
    transport = FakeTransport([current])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match=reason):
        provider.merge_pull_request(
            "acme/widget",
            12,
            merge_method="squash",
            expected_head_sha="d" * 40,
            expected_base_branch="main",
        )

    assert [call[0] for call in transport.calls] == ["GET"]


def test_merge_pull_request_blocks_base_drift_before_put():
    transport = FakeTransport([{
        "head": {"sha": "d" * 40},
        "base": {"ref": "release"},
        "state": "open",
        "merged": False,
        "draft": False,
    }])
    provider = GitHubSCMProvider(transport, git_service=FakeGitService())

    with pytest.raises(GitHubAPIError, match="head or base changed"):
        provider.merge_pull_request(
            "acme/widget",
            12,
            merge_method="squash",
            expected_head_sha="d" * 40,
            expected_base_branch="main",
        )

    assert [call[0] for call in transport.calls] == ["GET"]


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
            return json.dumps({"message": "Resource not accessible: host-secret-token"}).encode()

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
            self.heads = iter(["f" * 40])

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
