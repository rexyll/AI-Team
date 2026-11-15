"""Host-only GitHub SCM configuration and lifecycle factory.

Credentials are read from the process environment and remain inside the REST
transport. This module never places the token in Agent/task context.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping

from runtime.github_scm_provider import GitHubRESTTransport, GitHubSCMProvider
from runtime.scm_provider import SCMApprovalAuthority, SCMService


TOKEN_ENV = "AI_TEAM_GITHUB_TOKEN"
REPOSITORY_ENV = "AI_TEAM_GITHUB_REPOSITORY"
PULL_REQUEST_ENV = "AI_TEAM_GITHUB_PULL_REQUEST"


class GitHubSCMConfigurationError(ValueError):
    """Invalid or incomplete host-side GitHub SCM configuration."""


@dataclass(frozen=True)
class GitHubSCMRuntime:
    """Short-lived host-owned SCM runtime; repr intentionally hides service."""

    service: SCMService = field(repr=False)
    repository: str
    pull_request_number: int | None
    approval_authority: SCMApprovalAuthority = field(repr=False)


def create_github_scm_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    transport_factory: Callable[[str], object] | None = None,
    pull_request_number: int | None = None,
    require_pull_request: bool = True,
) -> GitHubSCMRuntime | None:
    """Build an opt-in GitHub SCM service from host environment variables.

    No configuration means disabled. Partial repository/PR configuration is
    rejected rather than silently disabling observation. The token is never
    returned, logged, or copied into orchestration context.
    """
    env = os.environ if environ is None else environ
    repository = (env.get(REPOSITORY_ENV) or "").strip()
    pull_request_raw = (env.get(PULL_REQUEST_ENV) or "").strip()
    token = (env.get(TOKEN_ENV) or "").strip()
    if pull_request_number is not None:
        if (
            not isinstance(pull_request_number, int)
            or isinstance(pull_request_number, bool)
            or pull_request_number < 1
        ):
            raise GitHubSCMConfigurationError("pull_request_number must be a positive integer")
        pull_request_raw = str(pull_request_number)

    if not repository and not pull_request_raw and not token:
        return None
    if not isinstance(require_pull_request, bool):
        raise GitHubSCMConfigurationError("require_pull_request must be a bool")
    if not repository or (require_pull_request and not pull_request_raw):
        raise GitHubSCMConfigurationError(
            f"{REPOSITORY_ENV} and a pull request number must be configured"
        )
    if not token:
        raise GitHubSCMConfigurationError(
            f"{TOKEN_ENV} is required when GitHub SCM observation is enabled"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise GitHubSCMConfigurationError(
            f"{REPOSITORY_ENV} must use owner/name format"
        )
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise GitHubSCMConfigurationError("GitHub repository path is invalid")
    if pull_request_raw and (
        not pull_request_raw.isdecimal() or int(pull_request_raw) < 1
    ):
        raise GitHubSCMConfigurationError(
            f"{PULL_REQUEST_ENV} must be a positive integer"
        )

    factory = transport_factory or (lambda secret: GitHubRESTTransport(secret))
    transport = factory(token)
    provider = GitHubSCMProvider(transport)  # type: ignore[arg-type]
    approval_authority = SCMApprovalAuthority()
    service = SCMService(provider, approval_authority)
    return GitHubSCMRuntime(
        service=service,
        repository=repository,
        pull_request_number=int(pull_request_raw) if pull_request_raw else None,
        approval_authority=approval_authority,
    )
