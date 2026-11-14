"""Host-owned SCM provider contract and explicit write approval boundary.

Agents never receive provider credentials or an SCM write capability. The
orchestrator obtains a short-lived, one-use approval token from the host and
passes it to SCMService for the exact repository/operation/target.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


_WRITE_OPERATIONS = frozenset({
    "push_branch",
    "create_or_update_pull_request",
    "merge_pull_request",
})
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


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

    token: str
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
        self, repository: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]: ...

    def get_pull_request(self, repository: str, pull_request_number: int) -> dict[str, Any]: ...

    def get_ci_status(self, repository: str, commit_sha: str) -> dict[str, Any]: ...

    def get_review_status(self, repository: str, pull_request_number: int) -> dict[str, Any]: ...

    def merge_pull_request(
        self, repository: str, pull_request_number: int, *, merge_method: str, expected_head_sha: str
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
        return self._provider.push_branch(
            repository, local_repository, branch, expected_head_sha=head_sha
        )

    def create_or_update_pull_request(
        self,
        repository: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        approval: SCMApproval | None,
    ) -> dict[str, Any]:
        repository = _repository(repository)
        head = _non_empty(head, "head")
        base = _non_empty(base, "base")
        title = _non_empty(title, "title")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        target = f"{head}:{base}"
        self._approvals.consume(
            approval,
            operation="create_or_update_pull_request",
            repository=repository,
            target=target,
        )
        return self._provider.create_or_update_pull_request(
            repository, head=head, base=base, title=title, body=body
        )

    def get_ci_status(self, repository: str, commit_sha: str) -> dict[str, Any]:
        repository = _repository(repository)
        if not isinstance(commit_sha, str) or not _SHA.fullmatch(commit_sha):
            raise ValueError("commit_sha must be a 7-64 character hexadecimal SHA")
        return self._provider.get_ci_status(repository, commit_sha)

    def get_review_status(self, repository: str, pull_request_number: int) -> dict[str, Any]:
        repository = _repository(repository)
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        return self._provider.get_review_status(repository, pull_request_number)

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
        head_sha = self._provider_pr_head(repository, pull_request_number)
        ci = self.get_ci_status(repository, head_sha)
        review = self.get_review_status(repository, pull_request_number)
        if ci.get("status") != "success":
            raise SCMPreflightError("merge blocked: CI status is not success")
        if review.get("status") != "approved":
            raise SCMPreflightError("merge blocked: review status is not approved")
        self._approvals.consume(
            approval,
            operation="merge_pull_request",
            repository=repository,
            target=f"{pull_request_number}:{head_sha}",
        )
        return self._provider.merge_pull_request(
            repository, pull_request_number, merge_method=merge_method, expected_head_sha=head_sha
        )

    def _provider_pr_head(self, repository: str, pull_request_number: int) -> str:
        getter = getattr(self._provider, "get_pull_request", None)
        if not callable(getter):
            raise SCMPreflightError("provider does not expose pull request head metadata")
        pull_request = getter(repository, pull_request_number)
        head = pull_request.get("head_sha") if isinstance(pull_request, dict) else None
        if not isinstance(head, str) or not _SHA.fullmatch(head):
            raise SCMPreflightError("provider returned no valid pull request head SHA")
        return head
