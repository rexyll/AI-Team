from __future__ import annotations

from runtime.scm_lifecycle import SCMLifecycleConfig, SCMLifecycleCoordinator
from runtime.scm_provider import SCMApprovalAuthority, SCMService


class FakeProvider:
    def __init__(self, *, ci="pending", review="pending", draft=False):
        self.calls = []
        self.ci = ci
        self.review = review
        self.draft = draft
        self.head = "a" * 40
        self.local_head = "c" * 40

    def get_local_head_sha(self, local_repository):
        self.calls.append(("local_head", local_repository))
        return self.local_head

    def push_branch(self, repository, local_repository, branch, *, expected_head_sha):
        self.calls.append(("push", repository, branch, expected_head_sha))
        return {"status": "pushed", "branch": branch}

    def create_or_update_pull_request(self, repository, *, head, base, title, body):
        self.calls.append(("create_pr", repository, head, base, title, body))
        return {"status": "created", "number": 19}

    def get_pull_request(self, repository, pull_request_number):
        self.calls.append(("get_pr", repository, pull_request_number))
        return {
            "head_sha": self.head,
            "state": "open",
            "merged": False,
            "draft": self.draft,
            "base_branch": "main",
        }

    def get_ci_status(self, repository, commit_sha):
        self.calls.append(("ci", repository, commit_sha))
        return {"status": self.ci}

    def get_review_status(self, repository, pull_request_number):
        self.calls.append(("review", repository, pull_request_number))
        return {"status": self.review}

    def merge_pull_request(self, repository, pull_request_number, *, merge_method, expected_head_sha):
        self.calls.append(("merge", repository, pull_request_number))
        return {"status": "merged"}


def _setup(*, ci="pending", review="pending", draft=False, attempts=3):
    provider = FakeProvider(ci=ci, review=review, draft=draft)
    authority = SCMApprovalAuthority()
    service = SCMService(provider, authority)
    config = SCMLifecycleConfig(
        repository="acme/widget",
        base_branch="main",
        max_poll_attempts=attempts,
        poll_interval_seconds=0,
    )
    sleeps = []
    coordinator = SCMLifecycleCoordinator(
        service, config, sleep=lambda seconds: sleeps.append(seconds)
    )
    return coordinator, provider, authority, sleeps


def test_publish_requires_separate_explicit_push_and_pr_approvals():
    coordinator, provider, authority, _ = _setup()
    push = authority.issue(
        operation="push_branch",
        repository="acme/widget",
        target="feature/a:" + provider.local_head,
        approved_by="human:operator",
    )
    pr = authority.issue(
        operation="create_or_update_pull_request",
        repository="acme/widget",
        target="feature/a:main",
        approved_by="human:operator",
    )

    result = coordinator.publish_and_open_pull_request(
        local_repository="/workspace/widget",
        head_branch="feature/a",
        title="Feature A",
        body="Implementation",
        push_approval=push,
        pull_request_approval=pr,
    )

    assert result["status"] == "published"
    assert result["pull_request"]["number"] == 19
    assert [call[0] for call in provider.calls] == [
        "local_head", "push", "create_pr"
    ]


def test_poll_returns_ready_only_for_open_pr_green_ci_and_approved_review():
    coordinator, provider, _, _ = _setup(ci="success", review="approved")

    result = coordinator.poll_pull_request(19)

    assert result["status"] == "ready"
    assert result["head_sha"] == "a" * 40
    assert result["attempt"] == 1
    assert not any(call[0] in {"push", "create_pr", "merge"} for call in provider.calls)


def test_poll_blocks_draft_pr_even_when_ci_and_review_are_green():
    coordinator, provider, _, _ = _setup(ci="success", review="approved", draft=True)

    result = coordinator.poll_pull_request(19)

    assert result["status"] == "draft"
    assert result["draft"] is True
    assert not any(call[0] in {"push", "create_pr", "merge"} for call in provider.calls)


def test_poll_stops_on_ci_failure_without_automatic_retry_or_write():
    coordinator, provider, _, sleeps = _setup(ci="failure", review="pending")

    result = coordinator.poll_pull_request(19)

    assert result["status"] == "ci_failed"
    assert result["attempt"] == 1
    assert sleeps == []
    assert not any(call[0] in {"push", "create_pr", "merge"} for call in provider.calls)


def test_poll_stops_on_changes_requested():
    coordinator, _, _, _ = _setup(ci="success", review="changes_requested")

    assert coordinator.poll_pull_request(19)["status"] == "changes_requested"


def test_poll_is_bounded_and_reports_timeout_for_pending_evidence():
    coordinator, provider, _, sleeps = _setup(attempts=3)

    result = coordinator.poll_pull_request(19)

    assert result["status"] == "timeout"
    assert result["attempt"] == 3
    assert len(sleeps) == 2
    assert len([call for call in provider.calls if call[0] == "get_pr"]) == 3


def test_config_rejects_unbounded_or_invalid_poll_settings():
    import pytest

    with pytest.raises(ValueError, match="max_poll_attempts"):
        SCMLifecycleConfig("acme/widget", max_poll_attempts=1000)
    with pytest.raises(ValueError, match="poll_interval_seconds"):
        SCMLifecycleConfig("acme/widget", poll_interval_seconds=301)
