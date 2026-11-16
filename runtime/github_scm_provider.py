"""GitHub SCM provider backed by host-owned credentials and Git transport."""
from __future__ import annotations

import json
import re
from datetime import datetime
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
        if not isinstance(api_base, str) or api_base.rstrip("/") != "https://api.github.com":
            raise ValueError("GitHub API base must be https://api.github.com")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._token = token.strip()
        self._api_base = api_base.rstrip("/")
        self._timeout = float(timeout_seconds)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not isinstance(method, str) or method.upper() not in {"GET", "POST", "PATCH", "PUT"}:
            raise ValueError("unsupported GitHub HTTP method")
        if (
            not isinstance(path, str)
            or not path.startswith("/repos/")
            or path.startswith("//")
            or chr(92) in path
            or ".." in path.split("?", 1)[0].split("/")
        ):
            raise ValueError("GitHub API path must be a safe repository-scoped path")
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
            # A remote error body is untrusted and may echo request material.
            # Never allow the host credential to appear in surfaced exceptions.
            if detail:
                detail = detail.replace(self._token, "[REDACTED]")
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
        owner, name = repository.split("/", 1)
        if owner in {".", ".."} or name in {".", ".."}:
            raise ValueError("repository owner and name cannot be dot path segments")
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

    def get_local_head_sha(self, local_repository: str) -> str:
        return self._git.head_commit(local_repository)

    def push_branch(
        self,
        repository: str,
        local_repository: str,
        branch: str,
        *,
        expected_head_sha: str,
    ) -> dict[str, Any]:
        self._repo_path(repository)
        if not isinstance(expected_head_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", expected_head_sha):
            raise ValueError("expected_head_sha must be a hexadecimal SHA")
        remote_url = self._git.remote_url(local_repository)
        if not self._remote_matches(remote_url, repository):
            raise PermissionError("origin remote does not match the approved GitHub repository")
        if self._git.head_commit(local_repository) != expected_head_sha:
            raise PermissionError("local HEAD changed after the push approval")
        output = self._git.push(local_repository, branch=branch, commit_sha=expected_head_sha)
        first_line = output.splitlines()[0] if output else ""
        if first_line != "exit_code=0":
            raise GitHubAPIError("git push failed; host output is intentionally redacted")
        return {
            "status": "pushed",
            "repository": repository,
            "branch": branch,
            "head_sha": expected_head_sha,
        }

    @staticmethod
    def _branch_ref_segment(branch: str) -> str:
        if (
            not isinstance(branch, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch)
            or branch.endswith((".", "/"))
            or "//" in branch
            or ".." in branch
            or "@{" in branch
            or any(part in {"", ".", ".."} for part in branch.split("/"))
        ):
            raise ValueError("head must be a safe local branch name")
        return urllib.parse.quote(branch, safe="/")

    def _remote_branch_sha(self, repository: str, branch: str) -> str:
        path = f"{self._repo_path(repository)}/git/ref/heads/{self._branch_ref_segment(branch)}"
        result = self._transport.request("GET", path)
        object_data = result.get("object") if isinstance(result, dict) else None
        sha = object_data.get("sha") if isinstance(object_data, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
            raise GitHubAPIError("GitHub returned an invalid remote branch reference")
        return sha

    def create_or_update_pull_request(
        self,
        repository: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> dict[str, Any]:
        root = self._repo_path(repository)
        for name, value in (("base", base), ("title", title)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(body, str):
            raise TypeError("body must be a string")
        if not isinstance(expected_head_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", expected_head_sha):
            raise ValueError("expected_head_sha must be a hexadecimal SHA")
        expected_sha = expected_head_sha.lower()
        # A PR API takes a mutable branch name, not a commit SHA. Anchor the
        # approval to the remote ref, then re-read it after the open-PR lookup
        # immediately before POST/PATCH.
        initial_sha = self._remote_branch_sha(repository, head)
        if initial_sha.lower() != expected_sha:
            raise GitHubAPIError("remote head branch SHA changed after PR approval")

        query = urllib.parse.urlencode({
            "state": "open",
            "head": f"{repository.split('/')[0]}:{head}",
            "base": base,
        })
        existing = self._transport.request("GET", f"{root}/pulls?{query}")
        if not isinstance(existing, list) or any(not isinstance(item, dict) for item in existing):
            raise GitHubAPIError("GitHub returned an invalid open pull request lookup response")
        if len(existing) > 1:
            raise GitHubAPIError("GitHub returned multiple open pull requests for the requested head/base")
        existing_number: int | None = None
        if existing:
            existing_number = existing[0].get("number")
            existing_head = existing[0].get("head")
            existing_head_sha = existing_head.get("sha") if isinstance(existing_head, dict) else None
            if (
                not isinstance(existing_number, int)
                or isinstance(existing_number, bool)
                or existing_number < 1
                or not isinstance(existing_head_sha, str)
                or not re.fullmatch(r"[0-9a-fA-F]{7,64}", existing_head_sha)
            ):
                raise GitHubAPIError("GitHub returned incomplete open pull request metadata")
            if existing_head_sha.lower() != expected_sha:
                raise GitHubAPIError("existing pull request head SHA does not match the approved commit")

        current_sha = self._remote_branch_sha(repository, head)
        if current_sha.lower() != expected_sha:
            raise GitHubAPIError("remote head branch SHA changed before PR write")

        if existing_number is not None:
            result = self._transport.request(
                "PATCH",
                f"{root}/pulls/{existing_number}",
                {"title": title, "body": body, "base": base},
            )
            action = "updated"
        else:
            result = self._transport.request(
                "POST",
                f"{root}/pulls",
                {"head": head, "base": base, "title": title, "body": body},
            )
            action = "created"
        result_number = result.get("number") if isinstance(result, dict) else None
        if (
            not isinstance(result_number, int)
            or isinstance(result_number, bool)
            or result_number < 1
            or (existing_number is not None and result_number != existing_number)
        ):
            raise GitHubAPIError("GitHub returned an invalid pull request response")
        result_head = result.get("head") if isinstance(result, dict) else None
        result_head_sha = result_head.get("sha") if isinstance(result_head, dict) else None
        if (
            not isinstance(result_head_sha, str)
            or not re.fullmatch(r"[0-9a-fA-F]{7,64}", result_head_sha)
            or result_head_sha.lower() != expected_sha
        ):
            raise GitHubAPIError(
                "GitHub PR write response head SHA does not match the approved commit"
            )
        return {
            "status": action,
            "number": result_number,
            "url": result.get("html_url"),
            "head": head,
            "base": base,
            "head_sha": expected_sha,
        }

    def get_pull_request(self, repository: str, pull_request_number: int) -> dict[str, Any]:
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be positive")
        result = self._transport.request(
            "GET", f"{self._repo_path(repository)}/pulls/{pull_request_number}"
        )
        head = result.get("head") if isinstance(result, dict) else None
        sha = head.get("sha") if isinstance(head, dict) else None
        state = result.get("state") if isinstance(result, dict) else None
        merged = result.get("merged") if isinstance(result, dict) else None
        draft = result.get("draft") if isinstance(result, dict) else None
        base = result.get("base") if isinstance(result, dict) else None
        base_branch = base.get("ref") if isinstance(base, dict) else None
        user = result.get("user") if isinstance(result, dict) else None
        author_login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
            raise GitHubAPIError("GitHub returned no valid pull request head SHA")
        if (
            state not in {"open", "closed"}
            or not isinstance(merged, bool)
            or not isinstance(draft, bool)
            or not isinstance(base_branch, str)
            or not base_branch.strip()
            or not isinstance(author_login, str)
            or not author_login.strip()
        ):
            raise GitHubAPIError("GitHub returned incomplete pull request state metadata")
        return {
            "head_sha": sha,
            "state": state,
            "merged": merged,
            "draft": draft,
            "base_branch": base_branch,
            "author_login": author_login,
        }

    def get_ci_status(self, repository: str, commit_sha: str) -> dict[str, Any]:
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise ValueError("commit_sha must be a hexadecimal SHA")
        root = self._repo_path(repository)
        check_runs: list[dict[str, Any]] = []
        checks_complete = False
        for page in range(1, 11):
            checks = self._transport.request(
                "GET",
                f"{root}/commits/{commit_sha}/check-runs?per_page=100&page={page}",
            )
            page_runs = checks.get("check_runs") if isinstance(checks, dict) else None
            if not isinstance(page_runs, list) or any(
                not isinstance(item, dict) for item in page_runs
            ):
                raise GitHubAPIError("GitHub returned an invalid check-run response")
            check_runs.extend(page_runs)
            if len(page_runs) < 100:
                checks_complete = True
                break

        combined = self._transport.request("GET", f"{root}/commits/{commit_sha}/status")
        if not isinstance(combined, dict):
            raise GitHubAPIError("GitHub returned an invalid combined status response")
        statuses = combined.get("statuses")
        if not isinstance(statuses, list) or any(not isinstance(item, dict) for item in statuses):
            raise GitHubAPIError("GitHub returned an invalid commit status list")

        accepted_conclusions = {"success", "neutral", "skipped"}
        failed_conclusions = {
            "action_required",
            "cancelled",
            "failure",
            "stale",
            "startup_failure",
            "timed_out",
        }
        pending_states = {"queued", "in_progress", "requested", "waiting", "pending"}
        failed_statuses = {"failure", "error"}
        check_failed = False
        check_pending = False
        check_unknown = False
        for check in check_runs:
            run_status = check.get("status")
            conclusion = check.get("conclusion")
            if run_status == "completed":
                if not isinstance(conclusion, str):
                    check_unknown = True
                elif conclusion.lower() in failed_conclusions:
                    check_failed = True
                elif conclusion.lower() not in accepted_conclusions:
                    check_unknown = True
            elif isinstance(run_status, str) and run_status.lower() in pending_states:
                check_pending = True
            else:
                check_unknown = True

        status_values: list[str] = []
        for item in statuses:
            value = item.get("state")
            if not isinstance(value, str):
                check_unknown = True
                continue
            status_values.append(value.lower())
        combined_state = combined.get("state")
        if isinstance(combined_state, str):
            normalized_combined_state = combined_state.lower()
            if normalized_combined_state in failed_statuses:
                status_values.append(normalized_combined_state)
            elif normalized_combined_state == "success":
                status_values.append(normalized_combined_state)
            elif normalized_combined_state in pending_states:
                # GitHub reports a synthetic "pending" combined state when
                # there are no legacy commit-status contexts. Do not let that
                # empty status collection override completed successful
                # Check Runs; when neither source has evidence, remain pending.
                if statuses or not check_runs:
                    status_values.append(normalized_combined_state)
            else:
                check_unknown = True
        else:
            check_unknown = True

        if check_failed or any(value in failed_statuses for value in status_values):
            status = "failure"
        elif not checks_complete or check_unknown:
            status = "unknown"
        elif check_pending or any(value in pending_states for value in status_values):
            status = "pending"
        elif (
            (check_runs or statuses or normalized_combined_state == "success")
            and all(
                str(item.get("conclusion") or item.get("status") or "").lower()
                in accepted_conclusions
                for item in check_runs
            )
            and all(value == "success" for value in status_values)
        ):
            status = "success"
        else:
            status = "unknown"
        return {
            "status": status,
            "check_runs": check_runs,
            "commit_status": combined.get("state"),
            "checks_complete": checks_complete,
        }

    def get_review_status(self, repository: str, pull_request_number: int) -> dict[str, Any]:
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be positive")
        reviews: list[dict[str, Any]] = []
        reviews_complete = False
        for page in range(1, 11):
            page_reviews = self._transport.request(
                "GET",
                f"{self._repo_path(repository)}/pulls/{pull_request_number}/reviews?per_page=100&page={page}",
            )
            if not isinstance(page_reviews, list) or any(
                not isinstance(item, dict) for item in page_reviews
            ):
                raise GitHubAPIError("GitHub returned an invalid pull request review response")
            reviews.extend(page_reviews)
            if len(page_reviews) < 100:
                reviews_complete = True
                break

        # Validate the complete review response before making any dependent
        # request. Malformed evidence must fail closed without being masked by a
        # later transport error while fetching PR metadata.
        review_timestamps: dict[int, datetime | None] = {}
        for review in reviews:
            user = review.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            state = review.get("state")
            submitted_at = review.get("submitted_at")
            commit_id = review.get("commit_id")
            if not isinstance(login, str) or not login or not isinstance(state, str):
                raise GitHubAPIError("GitHub returned incomplete pull request review metadata")
            normalized_state = state.upper()
            parsed_timestamp: datetime | None = None
            if normalized_state == "PENDING" and submitted_at is None:
                # A pending review has not been submitted and GitHub omits
                # submitted_at. It must never supersede a submitted review.
                parsed_timestamp = None
            else:
                if not isinstance(submitted_at, str) or not submitted_at.strip():
                    raise GitHubAPIError("GitHub returned an invalid review submission timestamp")
                try:
                    parsed_timestamp = datetime.fromisoformat(
                        submitted_at.strip().replace("Z", "+00:00")
                    )
                except ValueError:
                    raise GitHubAPIError(
                        "GitHub returned an invalid review submission timestamp"
                    ) from None
                if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
                    raise GitHubAPIError(
                        "GitHub returned an invalid review submission timestamp: timezone is required"
                    )
            if not isinstance(commit_id, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_id):
                raise GitHubAPIError("GitHub returned an invalid review commit SHA")
            review_timestamps[id(review)] = parsed_timestamp

        # Anchor the complete review set to the current PR head after pagination.
        # GitHub may retain an APPROVED review on an older commit when stale-review
        # dismissal is not enabled for the repository.
        pull_request = self.get_pull_request(repository, pull_request_number)
        current_head_sha = pull_request["head_sha"]
        pull_request_author = pull_request["author_login"]

        known_review_states = {
            "APPROVED",
            "CHANGES_REQUESTED",
            "COMMENTED",
            "DISMISSED",
            "PENDING",
        }
        latest_by_user: dict[str, tuple[datetime | None, dict[str, Any]]] = {}
        has_unknown_review_state = False
        for review in reviews:
            user = review["user"]
            login = user["login"]
            state = review["state"]
            commit_id = review["commit_id"]
            if commit_id.lower() != current_head_sha.lower():
                continue
            if login.casefold() == pull_request_author.casefold():
                continue
            normalized_state = state.upper()
            if normalized_state not in known_review_states:
                has_unknown_review_state = True
            previous = latest_by_user.get(login)
            submitted_at = review_timestamps[id(review)]
            if normalized_state == "PENDING":
                if previous is None:
                    latest_by_user[login] = (None, review)
                # Unsubmitted pending reviews have no timestamp and cannot
                # replace the reviewer's latest submitted decision.
                continue
            if submitted_at is None:
                # Non-PENDING states were validated before any metadata refresh.
                raise GitHubAPIError("GitHub returned an invalid review submission timestamp")
            if previous is None or previous[0] is None or submitted_at >= previous[0]:
                latest_by_user[login] = (submitted_at, review)

        states = [str(item[1].get("state") or "").upper() for item in latest_by_user.values()]
        status = (
            "pending"
            if not reviews_complete or has_unknown_review_state
            else "changes_requested"
            if "CHANGES_REQUESTED" in states
            else "approved"
            if "APPROVED" in states
            else "pending"
        )
        return {
            "status": status,
            "review_count": len(latest_by_user),
            "states": states,
            "reviews_complete": reviews_complete,
            "reviewed_head_sha": current_head_sha,
        }

    def merge_pull_request(
        self,
        repository: str,
        pull_request_number: int,
        *,
        merge_method: str,
        expected_head_sha: str,
        expected_base_branch: str,
    ) -> dict[str, Any]:
        if not isinstance(pull_request_number, int) or isinstance(pull_request_number, bool) or pull_request_number < 1:
            raise ValueError("pull_request_number must be positive")
        if merge_method not in {"merge", "squash", "rebase"}:
            raise ValueError("unsupported merge method")
        if not isinstance(expected_head_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", expected_head_sha):
            raise ValueError("expected_head_sha must be a hexadecimal SHA")
        if not isinstance(expected_base_branch, str) or not expected_base_branch.strip():
            raise ValueError("expected_base_branch must be non-empty")
        # Revalidate CI and current-head review evidence inside the adapter,
        # after the host approval preflight and immediately before the final PR
        # metadata read / merge write. GitHub has no atomic condition covering
        # these evidence sources together with the merge endpoint.
        ci = self.get_ci_status(repository, expected_head_sha)
        if not isinstance(ci, dict) or ci.get("status") != "success" or ci.get("checks_complete") is not True:
            raise GitHubAPIError("GitHub merge preflight requires successful, complete CI evidence")

        review = self.get_review_status(repository, pull_request_number)
        if (
            not isinstance(review, dict)
            or review.get("status") != "approved"
            or review.get("reviews_complete") is not True
            or not isinstance(review.get("reviewed_head_sha"), str)
            or review["reviewed_head_sha"].lower() != expected_head_sha.lower()
        ):
            raise GitHubAPIError("GitHub merge preflight requires an approved review on the expected head")

        # GitHub's merge endpoint supports an expected head SHA but no expected
        # base-ref precondition. Re-read the PR after the evidence refresh to
        # detect head/base/state changes immediately before the write.
        current = self.get_pull_request(repository, pull_request_number)
        if (
            current.get("state") != "open"
            or current.get("merged") is not False
            or current.get("draft") is not False
            or current.get("head_sha", "").lower() != expected_head_sha.lower()
            or current.get("base_branch") != expected_base_branch
        ):
            raise GitHubAPIError("GitHub pull request head or base changed after merge approval")
        result = self._transport.request(
            "PUT",
            f"{self._repo_path(repository)}/pulls/{pull_request_number}/merge",
            {"merge_method": merge_method, "sha": expected_head_sha},
        )
        if not isinstance(result, dict) or result.get("merged") is not True:
            message = result.get("message") if isinstance(result, dict) else ""
            raise GitHubAPIError("GitHub did not merge the pull request" + (f": {message}" if message else ""))
        return {"status": "merged", "sha": result.get("sha"), "message": result.get("message")}
