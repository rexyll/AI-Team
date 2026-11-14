"""GitHub SCM provider backed by host-owned credentials and Git transport."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from runtime.host_git import HostGitOperationService


class GitHubAPIError(RuntimeError):
    """Sanitized GitHub API failure without request headers or credentials."""


class GitHubTransport(Protocol):
    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any: ...


class GitHubRESTTransport:
    """Small GitHub REST client. The token is injected by host configuration."""

    def __init__(
        self,
        token: str,
        *,
        api_base: str = "https://api.github.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("GitHub token must be supplied by host configuration")
        if not isinstance(api_base, str) or not api_base.startswith("https://"):
            raise ValueError("GitHub API base must use HTTPS")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._token = token.strip()
        self._api_base = api_base.rstrip("/")
        self._timeout = float(timeout_seconds)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not isinstance(method, str) or method.upper() not in {"GET", "POST", "PATCH", "PUT"}:
            raise ValueError("unsupported GitHub HTTP method")
        if not isinstance(path, str) or not path.startswith("/repos/"):
            raise ValueError("GitHub API path must be repository-scoped")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self._api_base + path,
            data=body,
            method=method.upper(),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "AI-Team-SCM",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8", errors="replace")).get("message", "")
            except (ValueError, AttributeError):
                detail = ""
            raise GitHubAPIError(
                f"GitHub API request failed: HTTP {exc.code}" + (f" ({detail})" if detail else "")
            ) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GitHubAPIError(f"GitHub API request failed: {type(exc).__name__}") from None
        if not content:
            return {}
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise GitHubAPIError("GitHub API returned invalid JSON") from None


class GitHubSCMProvider:
    """GitHub implementation of the provider-neutral SCM contract."""

    def __init__(
        self,
        transport: GitHubTransport,
        *,
        git_service: HostGitOperationService | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("transport cannot be None")
        self._transport = transport
        self._git = git_service or HostGitOperationService()

    @staticmethod
    def _repo_path(repository: str) -> str:
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ValueError("repository must be an owner/name identifier")
        return "/repos/" + repository

    @staticmethod
    def _remote_matches(remote_url: str, repository: str) -> bool:
        value = remote_url.strip()
        if value.startswith("git@github.com:"):
            slug = value.split(":", 1)[1]
        else:
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme != "https" or (parsed.hostname or "").lower() != "github.com":
                return False
            slug = parsed.path.lstrip("/")
        slug = slug.removesuffix(".git").strip("/")
        return slug.lower() == repository.lower()

    def push_branch(self, repository: str, local_repository: str, branch: str) -> dict[str, Any]:
        self._repo_path(repository)
        remote_url = self._git.remote_url(local_repository)
        if not self._remote_matches(remote_url, repository):
            raise PermissionError("origin remote does not match the approved GitHub repository")
        output = self._git.push(local_repository, branch=branch)
        first_line = output.splitlines()[0] if output else ""
        if first_line != "exit_code=0":
            raise GitHubAPIError("git push failed: " + output[-1200:])
        return {"status": "pushed", "repository": repository, "branch": branch}

    def create_or_update_pull_request(
        self,
        repository: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        root = self._repo_path(repository)
        for name, value in (("head", head), ("base", base), ("title", title)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        query = urllib.parse.urlencode({
            "state": "open",
            "head": head if ":" in head else f"{repository.split('/')[0]}:{head}",
            "base": base,
        })
        existing = self._transport.request("GET", f"{root}/pulls?{query}")
        if isinstance(existing, list) and existing:
            number = existing[0].get("number")
            if not isinstance(number, int):
                raise GitHubAPIError("GitHub returned an invalid pull request number")
            result = self._transport.request(
                "PATCH", f"{root}/pulls/{number}", {"title": title, "body": body, "base": base}
            )
            action = "updated"
        else:
            result = self._transport.request(
                "POST", f"{root}/pulls", {"head": head, "base": base, "title": title, "body": body}
            )
            action = "created"
        if not isinstance(result, dict) or not isinstance(result.get("number"), int):
            raise GitHubAPIError("GitHub returned an invalid pull request response")
        return {
            "status": action,
            "number": result["number"],
            "url": result.get("html_url"),
            "head": head,
            "base": base,
        }

    def get_pull_request(self, repository: str, pull_request_number: int) -> dict[str, Any]:
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be positive")
        result = self._transport.request(
            "GET", f"{self._repo_path(repository)}/pulls/{pull_request_number}"
        )
        head = result.get("head") if isinstance(result, dict) else None
        sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
            raise GitHubAPIError("GitHub returned no valid pull request head SHA")
        return {"head_sha": sha, "state": result.get("state"), "merged": result.get("merged")}

    def get_ci_status(self, repository: str, commit_sha: str) -> dict[str, Any]:
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise ValueError("commit_sha must be a hexadecimal SHA")
        root = self._repo_path(repository)
        checks = self._transport.request(
            "GET", f"{root}/commits/{commit_sha}/check-runs?per_page=100"
        )
        combined = self._transport.request("GET", f"{root}/commits/{commit_sha}/status")
        check_runs = checks.get("check_runs", []) if isinstance(checks, dict) else []
        statuses = combined.get("statuses", []) if isinstance(combined, dict) else []
        conclusions = [
            str(item.get("conclusion") or item.get("status") or "").lower()
            for item in check_runs if isinstance(item, dict)
        ]
        state_values = [
            str(item.get("state") or "").lower()
            for item in statuses if isinstance(item, dict)
        ]
        if any(value in {"failure", "failed", "error"} for value in conclusions + state_values):
            status = "failure"
        elif any(value not in {"success", "neutral", "skipped"} for value in conclusions) or any(
            value == "pending" for value in state_values
        ):
            status = "pending"
        elif conclusions or state_values:
            status = "success" if all(
                value in {"success", "neutral", "skipped"} for value in conclusions
            ) and all(value == "success" for value in state_values) else "unknown"
        else:
            status = "unknown"
        return {
            "status": status,
            "check_runs": check_runs,
            "commit_status": combined.get("state") if isinstance(combined, dict) else None,
        }

    def get_review_status(self, repository: str, pull_request_number: int) -> dict[str, Any]:
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be positive")
        reviews = self._transport.request(
            "GET", f"{self._repo_path(repository)}/pulls/{pull_request_number}/reviews?per_page=100"
        )
        latest_by_user: dict[str, dict[str, Any]] = {}
        for review in reviews if isinstance(reviews, list) else []:
            if not isinstance(review, dict):
                continue
            user = review.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            if not isinstance(login, str):
                continue
            previous = latest_by_user.get(login)
            if previous is None or str(review.get("submitted_at") or "") >= str(previous.get("submitted_at") or ""):
                latest_by_user[login] = review
        states = [str(item.get("state") or "").upper() for item in latest_by_user.values()]
        status = (
            "changes_requested" if "CHANGES_REQUESTED" in states
            else "approved" if "APPROVED" in states
            else "pending"
        )
        return {"status": status, "review_count": len(latest_by_user), "states": states}

    def merge_pull_request(
        self, repository: str, pull_request_number: int, *, merge_method: str
    ) -> dict[str, Any]:
        if merge_method not in {"merge", "squash", "rebase"}:
            raise ValueError("unsupported merge method")
        result = self._transport.request(
            "PUT",
            f"{self._repo_path(repository)}/pulls/{pull_request_number}/merge",
            {"merge_method": merge_method},
        )
        if not isinstance(result, dict) or result.get("merged") is not True:
            message = result.get("message") if isinstance(result, dict) else ""
            raise GitHubAPIError("GitHub did not merge the pull request" + (f": {message}" if message else ""))
        return {"status": "merged", "sha": result.get("sha"), "message": result.get("message")}
