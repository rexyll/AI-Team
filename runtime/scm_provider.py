"""Host-owned SCM provider contract and explicit write approval boundary.

Agents never receive provider credentials or an SCM write capability. The
orchestrator obtains a short-lived, one-use approval token from the host and
passes it to SCMService for the exact repository/operation/target.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


_WRITE_OPERATIONS = frozenset({
    "push_branch",
    "create_or_update_pull_request",
    "merge_pull_request",
})
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


def scm_pull_request_approval_target(
    *, head: str, base: str, title: str, body: str, expected_head_sha: str
) -> str:
    """Bind a PR write approval to branch, exact pushed SHA and exact payload."""
    head = _non_empty(head, "head")
    base = _non_empty(base, "base")
    title = _non_empty(title, "title")
    if not isinstance(body, str):
        raise TypeError("body must be a string")
    if not isinstance(expected_head_sha, str) or not _SHA.fullmatch(expected_head_sha):
        raise ValueError("expected_head_sha must be a hexadecimal SHA")
    payload = json.dumps(
        {
            "head": head,
            "base": base,
            "title": title,
            "body": body,
            "expected_head_sha": expected_head_sha.lower(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"{head}:{base}:{expected_head_sha.lower()}:sha256={digest}"


def scm_merge_approval_target(
    pull_request_number: int,
    *,
    head_sha: str,
    base_branch: str,
    merge_method: str,
) -> str:
    """Bind a merge approval to PR identity, head, base and merge method."""
    if (
        not isinstance(pull_request_number, int)
        or isinstance(pull_request_number, bool)
        or pull_request_number < 1
    ):
        raise ValueError("pull_request_number must be a positive integer")
    if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
        raise ValueError("head_sha must be a hexadecimal SHA")
    base_branch = _non_empty(base_branch, "base_branch")
    if merge_method not in {"merge", "squash", "rebase"}:
        raise ValueError("merge_method must be merge, squash, or rebase")
    return f"{pull_request_number}:{head_sha}:{base_branch}:{merge_method}"


class SCMApprovalError(PermissionError):
    """An SCM write lacks a valid, scoped, unexpired host approval."""


class SCMPreflightError(RuntimeError):
    """A merge precondition (CI/review) is not satisfied."""


def _repository(value: str) -> str:
    if not isinstance(value, str) or not _REPOSITORY.fullmatch(value.strip()):
        raise ValueError("repository must be an owner/name identifier")
    owner, name = value.strip().split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ValueError("repository owner and name cannot be dot path segments")
    return value.strip()


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class SCMApproval:
    """Opaque one-use host approval scoped to one SCM write."""

    token: str = field(repr=False)
    operation: str
    repository: str
    target: str
    approved_by: str
    issued_at: str
    expires_at: str


class SCMApprovalAuthority:
    """Issues and consumes ephemeral host approvals; never exposed to Agents."""

    def __init__(self) -> None:
        self._issued: dict[str, SCMApproval] = {}

    def issue(
        self,
        *,
        operation: str,
        repository: str,
        target: str,
        approved_by: str,
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> SCMApproval:
        if operation not in _WRITE_OPERATIONS:
            raise ValueError(f"unsupported SCM write operation: {operation}")
        repository = _repository(repository)
        target = _non_empty(target, "target")
        approved_by = _non_empty(approved_by, "approved_by")
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        approval = SCMApproval(
            token=secrets.token_urlsafe(32),
            operation=operation,
            repository=repository,
            target=target,
            approved_by=approved_by,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
        )
        self._issued[approval.token] = approval
        return approval

    def consume(
        self,
        approval: SCMApproval | None,
        *,
        operation: str,
        repository: str,
        target: str,
        now: datetime | None = None,
    ) -> SCMApproval:
        if not isinstance(approval, SCMApproval):
            raise SCMApprovalError("explicit host approval is required")
        stored = self._issued.pop(approval.token, None)
        if stored is None or stored != approval:
            raise SCMApprovalError("approval is unknown, forged, or already consumed")
        if (
            approval.operation != operation
            or approval.repository != _repository(repository)
            or approval.target != _non_empty(target, "target")
        ):
            raise SCMApprovalError("approval scope does not match the requested SCM operation")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        expires = datetime.fromisoformat(approval.expires_at)
        if now > expires:
            raise SCMApprovalError("SCM approval has expired")
        return approval


class SCMProvider(Protocol):
    """Provider-neutral SCM operations. Implementations own credentials."""

    def get_local_head_sha(self, local_repository: str) -> str: ...

    def push_branch(
        self, repository: str, local_repository: str, branch: str, *, expected_head_sha: str
    ) -> dict[str, Any]: ...

    def create_or_update_pull_request(
        self,
        repository: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> dict[str, Any]: ...

    def get_pull_request(self, repository: str, pull_request_number: int) -> dict[str, Any]: ...

    def get_ci_status(self, repository: str, commit_sha: str) -> dict[str, Any]: ...

    def get_review_status(self, repository: str, pull_request_number: int) -> dict[str, Any]: ...

    def merge_pull_request(
        self,
        repository: str,
        pull_request_number: int,
        *,
        merge_method: str,
        expected_head_sha: str,
        expected_base_branch: str,
    ) -> dict[str, Any]: ...


class SCMService:
    """Host boundary that enforces approval and deterministic merge preflight."""

    def __init__(self, provider: SCMProvider, approval_authority: SCMApprovalAuthority) -> None:
        if provider is None:
            raise ValueError("provider cannot be None")
        if not isinstance(approval_authority, SCMApprovalAuthority):
            raise TypeError("approval_authority must be an SCMApprovalAuthority")
        self._provider = provider
        self._approvals = approval_authority

    def get_local_head_sha(self, local_repository: str) -> str:
        """Read the local HEAD SHA for an operator approval preview."""
        local_repository = _non_empty(local_repository, "local_repository")
        getter = getattr(self._provider, "get_local_head_sha", None)
        if not callable(getter):
            raise SCMPreflightError("provider does not expose local HEAD inspection")
        head_sha = getter(local_repository)
        if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
            raise SCMPreflightError("local repository returned no valid HEAD SHA")
        return head_sha

    def push_branch(
        self, repository: str, local_repository: str, branch: str, *, approval: SCMApproval | None
    ) -> dict[str, Any]:
        repository = _repository(repository)
        local_repository = _non_empty(local_repository, "local_repository")
        branch = _non_empty(branch, "branch")
        if (
            not isinstance(approval, SCMApproval)
            or approval.operation != "push_branch"
            or approval.repository != repository
            or not approval.target.startswith(f"{branch}:")
        ):
            raise SCMApprovalError("explicit host approval is required for this repository and branch")
        head_sha = self._provider.get_local_head_sha(local_repository)
        if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
            raise SCMPreflightError("local repository returned no valid HEAD SHA")
        self._approvals.consume(
            approval,
            operation="push_branch",
            repository=repository,
            target=f"{branch}:{head_sha}",
        )
        result = self._provider.push_branch(
            repository, local_repository, branch, expected_head_sha=head_sha
        )
        if not isinstance(result, dict) or result.get("status") != "pushed":
            raise SCMPreflightError("provider did not confirm the approved branch push")
        # The service, not provider-supplied metadata, anchors the published
        # branch to the exact SHA observed and approved immediately above.
        return {**result, "head_sha": head_sha}

    def create_or_update_pull_request(
        self,
        repository: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        expected_head_sha: str,
        approval: SCMApproval | None,
    ) -> dict[str, Any]:
        repository = _repository(repository)
        head = _non_empty(head, "head")
        base = _non_empty(base, "base")
        title = _non_empty(title, "title")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        if not isinstance(expected_head_sha, str) or not _SHA.fullmatch(expected_head_sha):
            raise ValueError("expected_head_sha must be a hexadecimal SHA")
        target = scm_pull_request_approval_target(
            head=head,
            base=base,
            title=title,
            body=body,
            expected_head_sha=expected_head_sha,
        )
        self._approvals.consume(
            approval,
            operation="create_or_update_pull_request",
            repository=repository,
            target=target,
        )
        result = self._provider.create_or_update_pull_request(
            repository,
            head=head,
            base=base,
            title=title,
            body=body,
            expected_head_sha=expected_head_sha,
        )
        result_head_sha = result.get("head_sha") if isinstance(result, dict) else None
        result_head = result.get("head") if isinstance(result, dict) else None
        result_base = result.get("base") if isinstance(result, dict) else None
        result_status = result.get("status") if isinstance(result, dict) else None
        result_number = result.get("number") if isinstance(result, dict) else None
        if (
            result_status not in {"created", "updated"}
            or not isinstance(result_number, int)
            or isinstance(result_number, bool)
            or result_number < 1
            or result_head != head
            or result_base != base
            or not isinstance(result_head_sha, str)
            or not _SHA.fullmatch(result_head_sha)
            or result_head_sha.lower() != expected_head_sha.lower()
        ):
            raise SCMPreflightError(
                "provider did not confirm a created/updated PR against the approved head/base/HEAD SHA"
            )
        return result

    def get_pull_request(self, repository: str, pull_request_number: int) -> dict[str, Any]:
        """Read the current PR head and state without granting a write capability."""
        repository = _repository(repository)
        if (
            not isinstance(pull_request_number, int)
            or isinstance(pull_request_number, bool)
            or pull_request_number < 1
        ):
            raise ValueError("pull_request_number must be a positive integer")
        getter = getattr(self._provider, "get_pull_request", None)
        if not callable(getter):
            raise SCMPreflightError("provider does not expose pull request metadata")
        result = getter(repository, pull_request_number)
        if not isinstance(result, dict):
            raise SCMPreflightError("provider returned invalid pull request metadata")
        head_sha = result.get("head_sha")
        if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
            raise SCMPreflightError("provider returned no valid pull request head SHA")
        state = result.get("state")
        merged = result.get("merged")
        draft = result.get("draft")
        base_branch = result.get("base_branch")
        if (
            state not in {"open", "closed"}
            or not isinstance(merged, bool)
            or not isinstance(draft, bool)
            or not isinstance(base_branch, str)
            or not base_branch.strip()
        ):
            raise SCMPreflightError("provider returned incomplete pull request state metadata")
        return {
            "head_sha": head_sha,
            "state": state,
            "merged": merged,
            "draft": draft,
            "base_branch": base_branch,
        }

    def get_ci_status(self, repository: str, commit_sha: str) -> dict[str, Any]:
        repository = _repository(repository)
        if not isinstance(commit_sha, str) or not _SHA.fullmatch(commit_sha):
            raise ValueError("commit_sha must be a 7-64 character hexadecimal SHA")
        result = self._provider.get_ci_status(repository, commit_sha)
        if not isinstance(result, dict):
            raise SCMPreflightError("provider returned invalid CI status metadata")
        normalized = dict(result)
        # A provider's positive CI result is not authoritative unless it
        # explicitly confirms that every bounded page was read. Keep concrete
        # failures/pending states, but never promote incomplete evidence.
        if normalized.get("status") == "success" and normalized.get("checks_complete") is not True:
            normalized["status"] = "unknown"
        return normalized

    def get_review_status(
        self,
        repository: str,
        pull_request_number: int,
        *,
        expected_head_sha: str | None = None,
    ) -> dict[str, Any]:
        repository = _repository(repository)
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        if expected_head_sha is not None and (
            not isinstance(expected_head_sha, str) or not _SHA.fullmatch(expected_head_sha)
        ):
            raise ValueError("expected_head_sha must be a 7-64 character hexadecimal SHA")
        result = self._provider.get_review_status(repository, pull_request_number)
        if not isinstance(result, dict):
            raise SCMPreflightError("provider returned invalid pull request review metadata")
        normalized = dict(result)
        # An approval is meaningful only when the provider confirms a complete
        # review read and supplies the head SHA to which those reviews apply.
        reviewed_head_sha = normalized.get("reviewed_head_sha")
        if normalized.get("status") == "approved" and (
            normalized.get("reviews_complete") is not True
            or not isinstance(reviewed_head_sha, str)
            or not _SHA.fullmatch(reviewed_head_sha)
        ):
            normalized["status"] = "pending"
        if expected_head_sha is not None:
            reviewed_head_sha = normalized.get("reviewed_head_sha")
            if (
                not isinstance(reviewed_head_sha, str)
                or not _SHA.fullmatch(reviewed_head_sha)
                or reviewed_head_sha.lower() != expected_head_sha.lower()
            ):
                # Never combine CI for one head with approval evidence for another.
                normalized["status"] = "pending"
                normalized["head_sha_match"] = False
            else:
                normalized["head_sha_match"] = True
        return normalized

    def merge_pull_request(
        self,
        repository: str,
        pull_request_number: int,
        *,
        approval: SCMApproval | None,
        merge_method: str = "squash",
    ) -> dict[str, Any]:
        repository = _repository(repository)
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        if merge_method not in {"merge", "squash", "rebase"}:
            raise ValueError("merge_method must be merge, squash, or rebase")
        if (
            not isinstance(approval, SCMApproval)
            or approval.operation != "merge_pull_request"
            or approval.repository != repository
            or not approval.target.startswith(f"{pull_request_number}:")
        ):
            raise SCMApprovalError("explicit host approval is required for this repository and pull request")
        head_sha, base_branch = self._provider_pr_target(repository, pull_request_number)
        ci = self.get_ci_status(repository, head_sha)
        review = self.get_review_status(
            repository, pull_request_number, expected_head_sha=head_sha
        )
        if ci.get("status") != "success" or ci.get("checks_complete") is not True:
            raise SCMPreflightError("merge blocked: CI status is not success with complete evidence")
        if (
            review.get("status") != "approved"
            or review.get("reviews_complete") is not True
            or review.get("head_sha_match") is not True
        ):
            raise SCMPreflightError("merge blocked: review status is not approved with complete current-head evidence")
        self._approvals.consume(
            approval,
            operation="merge_pull_request",
            repository=repository,
            target=scm_merge_approval_target(
                pull_request_number,
                head_sha=head_sha,
                base_branch=base_branch,
                merge_method=merge_method,
            ),
        )
        return self._provider.merge_pull_request(
            repository,
            pull_request_number,
            merge_method=merge_method,
            expected_head_sha=head_sha,
            expected_base_branch=base_branch,
        )

    def _provider_pr_target(self, repository: str, pull_request_number: int) -> tuple[str, str]:
        pull_request = self.get_pull_request(repository, pull_request_number)
        if pull_request.get("state") != "open" or pull_request.get("merged") is not False:
            raise SCMPreflightError("merge blocked: pull request is not open and unmerged")
        if pull_request.get("draft") is not False:
            raise SCMPreflightError("merge blocked: pull request is draft or draft state is unknown")
        return pull_request["head_sha"], pull_request["base_branch"]
