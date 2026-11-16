"""Host-owned, approval-gated SCM pull-request lifecycle coordination."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from runtime.scm_provider import SCMApproval, SCMService


@dataclass(frozen=True)
class SCMLifecycleConfig:
    repository: str
    base_branch: str = "main"
    max_poll_attempts: int = 12
    poll_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository)
            or any(part in {".", ".."} for part in self.repository.split("/", 1))
        ):
            raise ValueError("repository must use owner/name format")
        if not isinstance(self.base_branch, str) or not self.base_branch.strip():
            raise ValueError("base_branch must be non-empty")
        if (
            not isinstance(self.max_poll_attempts, int)
            or isinstance(self.max_poll_attempts, bool)
            or not 1 <= self.max_poll_attempts <= 120
        ):
            raise ValueError("max_poll_attempts must be between 1 and 120")
        if (
            not isinstance(self.poll_interval_seconds, (int, float))
            or isinstance(self.poll_interval_seconds, bool)
            or not 0 <= self.poll_interval_seconds <= 300
        ):
            raise ValueError("poll_interval_seconds must be between 0 and 300")


class SCMLifecycleCoordinator:
    """Coordinates host-authorized publication and bounded read-only polling.

    This class does not issue approvals. The caller must obtain distinct,
    one-use approvals from an explicit human authorization flow.
    """

    def __init__(
        self,
        service: SCMService,
        config: SCMLifecycleConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(service, SCMService):
            raise TypeError("service must be an SCMService")
        self._service = service
        self._config = config
        self._sleep = sleep

    def publish_and_open_pull_request(
        self,
        *,
        local_repository: str,
        head_branch: str,
        title: str,
        body: str,
        push_approval: SCMApproval,
        pull_request_approval: SCMApproval,
    ) -> dict[str, Any]:
        """Push the exact approved HEAD, then create/update its PR."""
        pushed = self._service.push_branch(
            self._config.repository,
            local_repository,
            head_branch,
            approval=push_approval,
        )
        pull_request = self._service.create_or_update_pull_request(
            self._config.repository,
            head=head_branch,
            base=self._config.base_branch,
            title=title,
            body=body,
            approval=pull_request_approval,
        )
        return {
            "status": "published",
            "repository": self._config.repository,
            "head_branch": head_branch,
            "base_branch": self._config.base_branch,
            "push": pushed,
            "pull_request": pull_request,
        }

    def poll_pull_request(self, pull_request_number: int) -> dict[str, Any]:
        """Poll PR/CI/review evidence with a strict attempt bound.

        No CI failure is automatically retried and no review decision is
        changed. The caller receives a stable terminal/timeout observation.
        """
        if (
            not isinstance(pull_request_number, int)
            or isinstance(pull_request_number, bool)
            or pull_request_number < 1
        ):
            raise ValueError("pull_request_number must be a positive integer")

        latest: dict[str, Any] = {}
        for attempt in range(1, self._config.max_poll_attempts + 1):
            pr = self._service.get_pull_request(
                self._config.repository, pull_request_number
            )
            ci = self._service.get_ci_status(
                self._config.repository, pr["head_sha"]
            )
            review = self._service.get_review_status(
                self._config.repository, pull_request_number
            )
            pr_open = pr.get("state") == "open" and pr.get("merged") is False
            ci_status = ci.get("status", "unknown")
            review_status = review.get("status", "unknown")

            if not pr_open:
                state = "closed"
            elif pr.get("draft") is not False:
                state = "draft"
            elif ci_status == "failure":
                state = "ci_failed"
            elif review_status == "changes_requested":
                state = "changes_requested"
            elif ci_status == "success" and review_status == "approved":
                state = "ready"
            else:
                state = "pending"

            latest = {
                "status": state,
                "repository": self._config.repository,
                "pull_request_number": pull_request_number,
                "head_sha": pr["head_sha"],
                "base_branch": pr["base_branch"],
                "pull_request_state": pr.get("state"),
                "merged": pr.get("merged"),
                "draft": pr.get("draft"),
                "ci_status": ci_status,
                "review_status": review_status,
                "attempt": attempt,
                "max_attempts": self._config.max_poll_attempts,
            }
            if state != "pending":
                return latest
            if attempt < self._config.max_poll_attempts:
                self._sleep(self._config.poll_interval_seconds)

        latest["status"] = "timeout"
        return latest
