from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.scm_provider import (
    SCMApprovalAuthority,
    SCMApprovalError,
    SCMPreflightError,
    SCMService,
    scm_merge_approval_target,
    scm_pull_request_approval_target,
)


class FakeSCMProvider:
    def __init__(self):
        self.calls = []
        self.ci = {"status": "success"}
        self.review = {"status": "approved"}
        self.pr = {"head_sha": "a" * 40, "state": "open", "merged": False, "draft": False, "base_branch": "main"}
        self.local_head = "c" * 40

    def get_local_head_sha(self, local_repository):
        self.calls.append(("local_head", local_repository))
        return self.local_head

    def push_branch(self, repository, local_repository, branch, *, expected_head_sha):
        self.calls.append(("push_branch", repository, local_repository, branch, expected_head_sha))
        return {"status": "pushed", "branch": branch}

    def create_or_update_pull_request(self, repository, *, head, base, title, body):
        self.calls.append(("create_pr", repository, head, base, title, body))
        return {"status": "created", "number": 7}

    def get_pull_request(self, repository, pull_request_number):
        self.calls.append(("get_pr", repository, pull_request_number))
        return self.pr

    def get_ci_status(self, repository, commit_sha):
        self.calls.append(("ci", repository, commit_sha))
        return self.ci

    def get_review_status(self, repository, pull_request_number):
        self.calls.append(("review", repository, pull_request_number))
        return self.review

    def merge_pull_request(
        self, repository, pull_request_number, *, merge_method, expected_head_sha, expected_base_branch
    ):
        self.calls.append(("merge", repository, pull_request_number, merge_method, expected_head_sha, expected_base_branch))
        return {"status": "merged", "number": pull_request_number}


def _service():
    provider = FakeSCMProvider()
    authority = SCMApprovalAuthority()
    return SCMService(provider, authority), provider, authority


def _approval(authority, operation, target, *, repository="acme/widget"):
    return authority.issue(
        operation=operation,
        repository=repository,
        target=target,
        approved_by="human:release-operator",
    )


def test_push_requires_exact_one_use_host_approval():
    service, provider, authority = _service()

    with pytest.raises(SCMApprovalError):
        service.push_branch("acme/widget", "/workspace/widget", "release/1.2", approval=None)

    approval = _approval(authority, "push_branch", "release/1.2:" + "c" * 40)
    result = service.push_branch(
        "acme/widget", "/workspace/widget", "release/1.2", approval=approval
    )
    assert result == {"status": "pushed", "branch": "release/1.2"}
    assert provider.calls == [("local_head", "/workspace/widget"), ("push_branch", "acme/widget", "/workspace/widget", "release/1.2", "c" * 40)]
    with pytest.raises(SCMApprovalError):
        service.push_branch("acme/widget", "/workspace/widget", "release/1.2", approval=approval)


def test_approval_is_bound_to_repository_operation_and_target():
    service, provider, authority = _service()
    approval = _approval(authority, "push_branch", "release/1.2:" + "c" * 40)

    with pytest.raises(SCMApprovalError, match="approval"):
        service.push_branch("acme/other", "/workspace/widget", "release/1.2", approval=approval)

    assert provider.calls == []


def test_pull_request_creation_requires_explicit_approval():
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "create_or_update_pull_request",
        scm_pull_request_approval_target(
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
        ),
    )

    result = service.create_or_update_pull_request(
        "acme/widget",
        head="feature/a",
        base="main",
        title="Feature A",
        body="Implementation summary",
        approval=approval,
    )

    assert result == {"status": "created", "number": 7}
    assert provider.calls == [
        ("create_pr", "acme/widget", "feature/a", "main", "Feature A", "Implementation summary")
    ]


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("Changed title", "Implementation summary"),
        ("Feature A", "Changed implementation summary"),
    ],
)
def test_pr_write_approval_is_bound_to_exact_title_and_body(title, body):
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "create_or_update_pull_request",
        scm_pull_request_approval_target(
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
        ),
    )

    with pytest.raises(SCMApprovalError, match="scope"):
        service.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title=title,
            body=body,
            approval=approval,
        )

    assert not any(call[0] == "create_pr" for call in provider.calls)


def test_pull_request_metadata_is_available_through_read_only_service():
    service, provider, _ = _service()

    result = service.get_pull_request("acme/widget", 7)

    assert result == {
        "head_sha": "a" * 40,
        "state": "open",
        "merged": False,
        "draft": False,
        "base_branch": "main",
    }
    assert provider.calls == [("get_pr", "acme/widget", 7)]


def test_ci_and_review_reads_do_not_require_approval():
    service, provider, _ = _service()

    assert service.get_ci_status("acme/widget", "a" * 40) == {"status": "success"}
    assert service.get_review_status("acme/widget", 7) == {"status": "approved"}
    assert [call[0] for call in provider.calls] == ["ci", "review"]


@pytest.mark.parametrize(
    ("ci", "review", "expected"),
    [
        ({"status": "pending"}, {"status": "approved"}, "CI"),
        ({"status": "success"}, {"status": "changes_requested"}, "review"),
        ({"status": "unknown"}, {"status": "approved"}, "CI"),
    ],
)
def test_merge_preflight_blocks_before_consuming_approval(ci, review, expected):
    service, provider, authority = _service()
    provider.ci = ci
    provider.review = review
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )

    with pytest.raises(SCMPreflightError, match=expected):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    assert not any(call[0] == "merge" for call in provider.calls)
    # The preflight does not consume the human approval. Once evidence is green,
    # the same approval can still authorize the exact merge target.
    provider.ci = {"status": "success"}
    provider.review = {"status": "approved"}
    result = service.merge_pull_request("acme/widget", 7, approval=approval)
    assert result["status"] == "merged"


def test_merge_requires_pull_request_head_metadata_and_approval():
    service, provider, authority = _service()
    provider.pr = {"state": "open", "merged": False, "draft": False, "base_branch": "main"}
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )

    with pytest.raises(SCMPreflightError, match="head SHA"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    assert not any(call[0] == "merge" for call in provider.calls)


def test_approval_repr_does_not_expose_capability_token():
    authority = SCMApprovalAuthority()
    approval = _approval(authority, "push_branch", "release/1.2:" + "c" * 40)

    assert approval.token not in repr(approval)
    assert "push_branch" in repr(approval)


def test_expired_approval_is_rejected():
    service, provider, authority = _service()
    now = datetime.now(timezone.utc)
    approval = authority.issue(
        operation="push_branch",
        repository="acme/widget",
        target="main",
        approved_by="operator",
        ttl_seconds=1,
        now=now,
    )

    with pytest.raises(SCMApprovalError, match="expired"):
        authority.consume(
            approval,
            operation="push_branch",
            repository="acme/widget",
            target="main",
            now=now + timedelta(seconds=2),
        )


@pytest.mark.parametrize("sha", ["", "not-a-sha", "g" * 40])
def test_ci_status_rejects_invalid_commit_sha(sha):
    service, _, _ = _service()
    with pytest.raises(ValueError, match="commit_sha"):
        service.get_ci_status("acme/widget", sha)


def test_merge_rejects_invalid_method():
    service, _, _ = _service()
    with pytest.raises(ValueError, match="merge_method"):
        service.merge_pull_request("acme/widget", 7, approval=None, merge_method="force")


def test_merge_approval_is_bound_to_the_exact_head_sha():
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )
    provider.pr = {"head_sha": "b" * 40, "state": "open", "merged": False, "draft": False, "base_branch": "main"}

    with pytest.raises(SCMApprovalError, match="scope"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    assert not any(call[0] == "merge" for call in provider.calls)


def test_merge_approval_is_bound_to_the_exact_base_branch():
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )
    provider.pr = {
        "head_sha": "a" * 40,
        "state": "open",
        "merged": False,
        "draft": False,
        "base_branch": "release",
    }

    with pytest.raises(SCMApprovalError, match="scope"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    assert not any(call[0] == "merge" for call in provider.calls)


def test_merge_approval_is_bound_to_exact_merge_method():
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )

    with pytest.raises(SCMApprovalError, match="scope"):
        service.merge_pull_request(
            "acme/widget", 7, approval=approval, merge_method="rebase"
        )

    assert not any(call[0] == "merge" for call in provider.calls)


def test_merge_preflight_rejects_draft_pull_request():
    service, provider, authority = _service()
    provider.pr = {
        "head_sha": "a" * 40,
        "state": "open",
        "merged": False,
        "draft": True,
        "base_branch": "main",
    }
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )

    with pytest.raises(SCMPreflightError, match="draft"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    assert not any(call[0] == "merge" for call in provider.calls)


def test_local_head_sha_is_available_for_operator_approval_preview():
    service, provider, _ = _service()

    assert service.get_local_head_sha("/workspace/widget") == "c" * 40
    assert provider.calls == [("local_head", "/workspace/widget")]


def test_local_head_sha_rejects_invalid_provider_result():
    service, provider, _ = _service()
    provider.local_head = "not-a-sha"

    with pytest.raises(SCMPreflightError, match="valid HEAD SHA"):
        service.get_local_head_sha("/workspace/widget")


@pytest.mark.parametrize(
    "pr",
    [
        {"head_sha": "a" * 40, "state": "closed", "merged": False, "draft": False, "base_branch": "main"},
        {"head_sha": "a" * 40, "state": "open", "merged": True, "draft": False, "base_branch": "main"},
    ],
)
def test_merge_preflight_rejects_closed_or_already_merged_pr(pr):
    service, provider, authority = _service()
    provider.pr = pr
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )

    with pytest.raises(SCMPreflightError, match="not open and unmerged"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    assert not any(call[0] == "merge" for call in provider.calls)
