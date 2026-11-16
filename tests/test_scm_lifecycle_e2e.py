from __future__ import annotations

import pytest

from runtime.scm_lifecycle import SCMLifecycleConfig, SCMLifecycleCoordinator
from runtime.scm_provider import (
    SCMApprovalAuthority,
    SCMApprovalError,
    SCMPreflightError,
    SCMService,
    scm_merge_approval_target,
    scm_pull_request_approval_target,
)


class LifecycleProvider:
    """Deterministic fake provider used to exercise the complete SCM saga."""

    def __init__(self):
        self.events = []
        self.local_head = "c" * 40
        self.pr_head = "c" * 40
        self.pr_state = "open"
        self.merged = False
        self.draft = False
        self.base_branch = "main"
        self.ci = "success"
        self.review = "approved"
        self.fail_pr_create = False

    def get_local_head_sha(self, local_repository):
        self.events.append(("local_head", local_repository, self.local_head))
        return self.local_head

    def push_branch(self, repository, local_repository, branch, *, expected_head_sha):
        self.events.append(("push", repository, branch, expected_head_sha))
        if self.local_head != expected_head_sha:
            raise RuntimeError("local HEAD changed before push")
        return {"status": "pushed", "branch": branch, "sha": expected_head_sha}

    def create_or_update_pull_request(self, repository, *, head, base, title, body):
        self.events.append(("create_pr", repository, head, base))
        if self.fail_pr_create:
            raise RuntimeError("simulated PR API outage")
        return {"status": "created", "number": 23, "head_sha": self.pr_head}

    def get_pull_request(self, repository, pull_request_number):
        self.events.append(("get_pr", repository, pull_request_number))
        return {
            "head_sha": self.pr_head,
            "state": self.pr_state,
            "merged": self.merged,
            "draft": self.draft,
            "base_branch": self.base_branch,
        }

    def get_ci_status(self, repository, commit_sha):
        self.events.append(("ci", repository, commit_sha))
        return {"status": self.ci}

    def get_review_status(self, repository, pull_request_number):
        self.events.append(("review", repository, pull_request_number))
        return {"status": self.review}

    def merge_pull_request(
        self,
        repository,
        pull_request_number,
        *,
        merge_method,
        expected_head_sha,
        expected_base_branch,
    ):
        self.events.append(
            ("merge", repository, pull_request_number, merge_method, expected_head_sha, expected_base_branch)
        )
        if self.pr_head != expected_head_sha:
            raise RuntimeError("GitHub head SHA mismatch")
        if self.base_branch != expected_base_branch:
            raise RuntimeError("GitHub base branch mismatch")
        if self.pr_state != "open" or self.merged:
            raise RuntimeError("PR is no longer mergeable")
        self.merged = True
        return {"status": "merged", "sha": "d" * 40}


def _system():
    provider = LifecycleProvider()
    authority = SCMApprovalAuthority()
    service = SCMService(provider, authority)
    coordinator = SCMLifecycleCoordinator(
        service,
        SCMLifecycleConfig(
            repository="acme/widget",
            base_branch="main",
            max_poll_attempts=2,
            poll_interval_seconds=0,
        ),
        sleep=lambda _: None,
    )
    return provider, authority, service, coordinator


def _approval(authority, operation, target):
    return authority.issue(
        operation=operation,
        repository="acme/widget",
        target=target,
        approved_by="human:release-operator",
    )


def _publish(coordinator, authority, provider):
    push = _approval(
        authority, "push_branch", "feature/release:" + provider.local_head
    )
    pr = _approval(
        authority,
        "create_or_update_pull_request",
        scm_pull_request_approval_target(
            head="feature/release",
            base="main",
            title="Release feature",
            body="Validated implementation",
        ),
    )
    return coordinator.publish_and_open_pull_request(
        local_repository="/workspace/widget",
        head_branch="feature/release",
        title="Release feature",
        body="Validated implementation",
        push_approval=push,
        pull_request_approval=pr,
    )


def test_full_publish_poll_and_merge_lifecycle_is_ordered_and_auditable():
    provider, authority, service, coordinator = _system()

    published = _publish(coordinator, authority, provider)
    assert published["status"] == "published"
    assert published["pull_request"]["number"] == 23

    observation = coordinator.poll_pull_request(23)
    assert observation["status"] == "ready"
    assert observation["head_sha"] == provider.pr_head

    approval = _approval(
        authority, "merge_pull_request", scm_merge_approval_target(
            23,
            head_sha=observation["head_sha"],
            base_branch=observation["base_branch"],
            merge_method="squash",
        )
    )
    merged = service.merge_pull_request(
        "acme/widget", 23, approval=approval, merge_method="squash"
    )

    assert merged["status"] == "merged"
    assert provider.merged is True
    assert [event[0] for event in provider.events] == [
        "local_head",
        "push",
        "create_pr",
        "get_pr",
        "ci",
        "review",
        "get_pr",
        "ci",
        "review",
        "merge",
    ]
    assert provider.events[-1] == (
        "merge", "acme/widget", 23, "squash", provider.pr_head, "main"
    )


@pytest.mark.parametrize(
    ("ci", "review", "expected"),
    [
        ("failure", "approved", "ci_failed"),
        ("success", "changes_requested", "changes_requested"),
        ("pending", "approved", "timeout"),
    ],
)
def test_lifecycle_failure_evidence_never_reaches_merge_write(ci, review, expected):
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    provider.ci = ci
    provider.review = review

    observation = coordinator.poll_pull_request(23)

    assert observation["status"] == expected
    assert not any(event[0] == "merge" for event in provider.events)


def test_closed_pr_stops_lifecycle_before_merge():
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    provider.pr_state = "closed"

    observation = coordinator.poll_pull_request(23)

    assert observation["status"] == "closed"
    assert not any(event[0] == "merge" for event in provider.events)


def test_draft_pr_never_reaches_ready_or_merge():
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    provider.draft = True

    observation = coordinator.poll_pull_request(23)

    assert observation["status"] == "draft"
    assert not any(event[0] == "merge" for event in provider.events)


def test_head_sha_drift_after_poll_invalidates_merge_approval():
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    observation = coordinator.poll_pull_request(23)
    approval = _approval(
        authority, "merge_pull_request", scm_merge_approval_target(
            23,
            head_sha=observation["head_sha"],
            base_branch=observation["base_branch"],
            merge_method="squash",
        )
    )
    provider.pr_head = "e" * 40

    with pytest.raises(SCMApprovalError, match="scope"):
        service.merge_pull_request("acme/widget", 23, approval=approval)

    assert not any(event[0] == "merge" for event in provider.events)


def test_base_branch_drift_after_poll_invalidates_merge_approval():
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    observation = coordinator.poll_pull_request(23)
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            23,
            head_sha=observation["head_sha"],
            base_branch=observation["base_branch"],
            merge_method="squash",
        ),
    )
    provider.base_branch = "release"

    with pytest.raises(SCMApprovalError, match="scope"):
        service.merge_pull_request("acme/widget", 23, approval=approval)

    assert not any(event[0] == "merge" for event in provider.events)


def test_pr_closed_after_poll_is_rejected_by_fresh_merge_preflight():
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    observation = coordinator.poll_pull_request(23)
    approval = _approval(
        authority, "merge_pull_request", scm_merge_approval_target(
            23,
            head_sha=observation["head_sha"],
            base_branch=observation["base_branch"],
            merge_method="squash",
        )
    )
    provider.pr_state = "closed"

    with pytest.raises(SCMPreflightError, match="not open and unmerged"):
        service.merge_pull_request("acme/widget", 23, approval=approval)

    assert not any(event[0] == "merge" for event in provider.events)


def test_local_head_drift_invalidates_push_approval_before_any_write():
    provider, authority, service, coordinator = _system()
    approval = _approval(
        authority, "push_branch", "feature/release:" + provider.local_head
    )
    provider.local_head = "f" * 40

    with pytest.raises(SCMApprovalError, match="scope"):
        service.push_branch(
            "acme/widget",
            "/workspace/widget",
            "feature/release",
            approval=approval,
        )

    assert not any(event[0] == "push" for event in provider.events)
    assert not any(event[0] == "create_pr" for event in provider.events)


def test_pr_creation_failure_is_reported_after_push_without_hidden_retry():
    provider, authority, service, coordinator = _system()
    provider.fail_pr_create = True

    with pytest.raises(RuntimeError, match="PR API outage"):
        _publish(coordinator, authority, provider)

    assert [event[0] for event in provider.events] == [
        "local_head", "push", "create_pr"
    ]
    assert sum(event[0] == "push" for event in provider.events) == 1
    assert sum(event[0] == "create_pr" for event in provider.events) == 1


def test_merge_api_failure_is_propagated_without_automatic_retry():
    provider, authority, service, coordinator = _system()
    _publish(coordinator, authority, provider)
    observation = coordinator.poll_pull_request(23)
    approval = _approval(
        authority, "merge_pull_request", scm_merge_approval_target(
            23,
            head_sha=observation["head_sha"],
            base_branch=observation["base_branch"],
            merge_method="squash",
        )
    )

    def fail_merge(*args, **kwargs):
        provider.events.append(("merge_api_error",))
        raise RuntimeError("simulated merge API outage")

    provider.merge_pull_request = fail_merge

    with pytest.raises(RuntimeError, match="merge API outage"):
        service.merge_pull_request("acme/widget", 23, approval=approval)

    assert sum(event[0] == "merge_api_error" for event in provider.events) == 1
    assert not provider.merged
