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
        self.ci = {"status": "success", "checks_complete": True}
        self.review = {"status": "approved", "reviews_complete": True}
        self.pr = {"head_sha": "a" * 40, "state": "open", "merged": False, "draft": False, "base_branch": "main"}
        self.local_head = "c" * 40
        self.pr_write_head_sha = None

    def get_local_head_sha(self, local_repository):
        self.calls.append(("local_head", local_repository))
        return self.local_head

    def push_branch(self, repository, local_repository, branch, *, expected_head_sha):
        self.calls.append(("push_branch", repository, local_repository, branch, expected_head_sha))
        return {
            "status": "pushed",
            "repository": repository,
            "branch": branch,
            "head_sha": expected_head_sha,
        }

    def create_or_update_pull_request(self, repository, *, head, base, title, body, expected_head_sha):
        self.calls.append(("create_pr", repository, head, base, title, body, expected_head_sha))
        return {
            "status": "created",
            "number": 7,
            "head": head,
            "base": base,
            "head_sha": self.pr_write_head_sha or expected_head_sha,
        }

    def get_pull_request(self, repository, pull_request_number):
        self.calls.append(("get_pr", repository, pull_request_number))
        return self.pr

    def get_ci_status(self, repository, commit_sha):
        self.calls.append(("ci", repository, commit_sha))
        return self.ci

    def get_review_status(self, repository, pull_request_number):
        self.calls.append(("review", repository, pull_request_number))
        result = dict(self.review)
        result.setdefault("reviewed_head_sha", self.pr.get("head_sha", "a" * 40))
        return result

    def merge_pull_request(
        self, repository, pull_request_number, *, merge_method, expected_head_sha, expected_base_branch
    ):
        self.calls.append(("merge", repository, pull_request_number, merge_method, expected_head_sha, expected_base_branch))
        return {
            "status": "merged",
            "number": pull_request_number,
            "head_sha": expected_head_sha,
            "merge_sha": "d" * 40,
        }


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
    assert result == {"status": "pushed", "branch": "release/1.2", "head_sha": "c" * 40}
    assert provider.calls == [("local_head", "/workspace/widget"), ("push_branch", "acme/widget", "/workspace/widget", "release/1.2", "c" * 40)]
    with pytest.raises(SCMApprovalError):
        service.push_branch("acme/widget", "/workspace/widget", "release/1.2", approval=approval)


@pytest.mark.parametrize(
    "malformed_result",
    [
        {"status": "pushed", "repository": "acme/other", "branch": "release/1.2", "head_sha": "c" * 40},
        {"status": "pushed", "repository": "acme/widget", "branch": "release/other", "head_sha": "c" * 40},
        {"status": "pushed", "repository": "acme/widget", "branch": "release/1.2", "head_sha": "b" * 40},
        {"status": "pushed", "repository": "acme/widget", "branch": "release/1.2"},
        {"status": "failed", "repository": "acme/widget", "branch": "release/1.2", "head_sha": "c" * 40},
        None,
    ],
)
def test_push_fails_closed_on_malformed_provider_result(malformed_result):
    service, provider, authority = _service()
    provider.push_branch = lambda *args, **kwargs: malformed_result
    approval = _approval(authority, "push_branch", "release/1.2:" + "c" * 40)

    with pytest.raises(SCMPreflightError, match="exact approved repository/branch/HEAD push"):
        service.push_branch(
            "acme/widget", "/workspace/widget", "release/1.2", approval=approval
        )


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
            expected_head_sha="a" * 40,
        ),
    )

    result = service.create_or_update_pull_request(
        "acme/widget",
        head="feature/a",
        base="main",
        title="Feature A",
        body="Implementation summary",
        expected_head_sha="a" * 40,
        approval=approval,
    )

    assert result == {
        "status": "created",
        "number": 7,
        "head": "feature/a",
        "base": "main",
        "head_sha": "a" * 40,
    }
    assert provider.calls == [
        ("create_pr", "acme/widget", "feature/a", "main", "Feature A", "Implementation summary", "a" * 40)
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
            expected_head_sha="a" * 40,
        ),
    )

    with pytest.raises(SCMApprovalError, match="scope"):
        service.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title=title,
            body=body,
            expected_head_sha="a" * 40,
            approval=approval,
        )

    assert not any(call[0] == "create_pr" for call in provider.calls)


@pytest.mark.parametrize(
    "malformed_result",
    [
        {
            "status": "pending", "number": 7, "head": "feature/a",
            "base": "main", "head_sha": "a" * 40,
        },
        {
            "status": "created", "number": True, "head": "feature/a",
            "base": "main", "head_sha": "a" * 40,
        },
        {
            "status": "created", "number": 7, "head": "feature/a",
            "base": "main", "head_sha": "b" * 40,
        },
        {
            "status": "created", "number": 7, "head": "feature/other",
            "base": "main", "head_sha": "a" * 40,
        },
        {
            "status": "created", "number": 7, "head": "feature/a",
            "base": "release", "head_sha": "a" * 40,
        },
        {"status": "created", "number": 7, "head_sha": "a" * 40},
    ],
)
def test_pr_write_fails_closed_on_malformed_provider_result(malformed_result):
    service, provider, authority = _service()
    provider.create_or_update_pull_request = lambda *args, **kwargs: malformed_result
    approval = _approval(
        authority,
        "create_or_update_pull_request",
        scm_pull_request_approval_target(
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
            expected_head_sha="a" * 40,
        ),
    )

    with pytest.raises(SCMPreflightError, match="provider did not confirm a created/updated PR"):
        service.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
            expected_head_sha="a" * 40,
            approval=approval,
        )


def test_pr_write_fails_closed_when_provider_does_not_confirm_expected_sha():
    service, provider, authority = _service()
    provider.pr_write_head_sha = "b" * 40
    approval = _approval(
        authority,
        "create_or_update_pull_request",
        scm_pull_request_approval_target(
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
            expected_head_sha="a" * 40,
        ),
    )

    with pytest.raises(SCMPreflightError, match="approved head/base/HEAD SHA"):
        service.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
            expected_head_sha="a" * 40,
            approval=approval,
        )

    assert provider.calls[-1][0] == "create_pr"


def test_pr_write_approval_is_bound_to_exact_expected_head_sha():
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "create_or_update_pull_request",
        scm_pull_request_approval_target(
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
            expected_head_sha="a" * 40,
        ),
    )

    with pytest.raises(SCMApprovalError, match="scope"):
        service.create_or_update_pull_request(
            "acme/widget",
            head="feature/a",
            base="main",
            title="Feature A",
            body="Implementation summary",
            expected_head_sha="b" * 40,
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


def test_review_status_is_pending_when_review_anchor_does_not_match_expected_ci_head():
    service, provider, _ = _service()
    provider.review = {
        "status": "approved",
        "reviewed_head_sha": "b" * 40,
    }

    result = service.get_review_status(
        "acme/widget", 7, expected_head_sha="a" * 40
    )

    assert result["status"] == "pending"
    assert result["head_sha_match"] is False


def test_ci_and_review_reads_do_not_require_approval():
    service, provider, _ = _service()

    assert service.get_ci_status("acme/widget", "a" * 40) == {
        "status": "success",
        "checks_complete": True,
    }
    assert service.get_review_status("acme/widget", 7) == {
        "status": "approved",
        "reviews_complete": True,
        "reviewed_head_sha": "a" * 40,
    }
    assert [call[0] for call in provider.calls] == ["ci", "review"]


@pytest.mark.parametrize(
    ("ci", "review", "expected"),
    [
        ({"status": "pending", "checks_complete": True}, {"status": "approved", "reviews_complete": True}, "CI"),
        ({"status": "success", "checks_complete": True}, {"status": "changes_requested", "reviews_complete": True}, "review"),
        ({"status": "unknown", "checks_complete": True}, {"status": "approved", "reviews_complete": True}, "CI"),
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
    provider.ci = {"status": "success", "checks_complete": True}
    provider.review = {"status": "approved", "reviews_complete": True}
    result = service.merge_pull_request("acme/widget", 7, approval=approval)
    assert result["status"] == "merged"


@pytest.mark.parametrize(
    "incomplete_ci",
    [
        {"status": "success"},
        {"status": "success", "checks_complete": False},
        {"status": "success", "checks_complete": "true"},
    ],
)
def test_service_downgrades_incomplete_ci_success_to_unknown(incomplete_ci):
    service, provider, _ = _service()
    provider.ci = incomplete_ci

    result = service.get_ci_status("acme/widget", "a" * 40)

    assert result["status"] == "unknown"


@pytest.mark.parametrize(
    "incomplete_review",
    [
        {"status": "approved"},
        {"status": "approved", "reviews_complete": False},
        {"status": "approved", "reviews_complete": True, "reviewed_head_sha": "not-a-sha"},
    ],
)
def test_service_downgrades_unanchored_or_incomplete_review_approval(incomplete_review):
    service, provider, _ = _service()
    provider.review = incomplete_review

    result = service.get_review_status(
        "acme/widget", 7, expected_head_sha="a" * 40
    )

    assert result["status"] == "pending"


def test_merge_preflight_requires_explicit_complete_ci_and_review_evidence():
    service, provider, authority = _service()
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )
    provider.ci = {"status": "success", "checks_complete": False}
    provider.review = {"status": "approved", "reviews_complete": False}

    with pytest.raises(SCMPreflightError, match="CI status is not success"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    provider.ci = {"status": "success", "checks_complete": True}
    with pytest.raises(SCMPreflightError, match="review status is not approved"):
        service.merge_pull_request("acme/widget", 7, approval=approval)

    provider.review = {"status": "approved", "reviews_complete": True}
    assert service.merge_pull_request("acme/widget", 7, approval=approval)["status"] == "merged"


@pytest.mark.parametrize(
    "malformed_result",
    [
        {"status": "merged", "number": 8, "head_sha": "a" * 40, "merge_sha": "d" * 40},
        {"status": "merged", "number": 7, "head_sha": "b" * 40, "merge_sha": "d" * 40},
        {"status": "merged", "number": 7, "head_sha": "a" * 40, "merge_sha": "not-a-sha"},
        {"status": "pending", "number": 7, "head_sha": "a" * 40, "merge_sha": "d" * 40},
        {"status": "merged", "number": 7, "head_sha": "a" * 40},
        None,
    ],
)
def test_merge_fails_closed_on_malformed_provider_result(malformed_result):
    service, provider, authority = _service()
    provider.merge_pull_request = lambda *args, **kwargs: malformed_result
    approval = _approval(
        authority,
        "merge_pull_request",
        scm_merge_approval_target(
            7, head_sha="a" * 40, base_branch="main", merge_method="squash"
        ),
    )

    with pytest.raises(SCMPreflightError, match="approved PR merge and resulting merge SHA"):
        service.merge_pull_request("acme/widget", 7, approval=approval)


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
