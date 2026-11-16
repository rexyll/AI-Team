"""One-shot live GitHub SCM read-only integration probe.

This command uses only host-provided environment configuration. It never
pushes, creates/updates pull requests, changes reviews, or merges.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from runtime.github_scm_config import create_github_scm_runtime


def _safe_check_runs(value: Any) -> list[dict[str, Any]]:
    """Keep status metadata only; never emit remote output summaries/log text."""
    if not isinstance(value, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for key in ("name", "status", "conclusion", "started_at", "completed_at"):
            field = item.get(key)
            if isinstance(field, str):
                row[key] = field[:200]
        safe.append(row)
    return safe


def observe(
    service: Any,
    repository: str,
    pull_request_number: int,
    *,
    ci_probe_sha: str | None = None,
) -> dict[str, Any]:
    """Read PR/CI/review evidence and optionally validate Check Run-only aggregation."""
    pull_request = service.get_pull_request(repository, pull_request_number)
    head_sha = pull_request["head_sha"]
    ci = service.get_ci_status(repository, head_sha)
    review = service.get_review_status(
        repository, pull_request_number, expected_head_sha=head_sha
    )

    pull_request_open = (
        pull_request.get("state") == "open" and pull_request.get("merged") is False
    )
    pull_request_draft = pull_request.get("draft") is not False
    ci_status = ci.get("status", "unknown")
    review_status = review.get("status", "unknown")
    blockers: list[str] = []
    if not pull_request_open:
        blockers.append("pull_request_not_open")
    if pull_request_draft:
        blockers.append("pull_request_draft")
    if ci_status != "success":
        blockers.append("ci_not_success")
    if review_status != "approved":
        blockers.append("review_not_approved")

    ci_aggregation_probe = None
    if ci_probe_sha is not None:
        if not isinstance(ci_probe_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", ci_probe_sha):
            raise ValueError("ci_probe_sha must be a hexadecimal SHA")
        probe = service.get_ci_status(repository, ci_probe_sha)
        ci_aggregation_probe = {
            "sha": ci_probe_sha,
            "status": probe.get("status", "unknown"),
            "commit_status": probe.get("commit_status"),
            "checks_complete": probe.get("checks_complete", False),
            "check_run_count": len(probe.get("check_runs", []))
            if isinstance(probe.get("check_runs"), list) else 0,
        }

    return {
        "schema_version": 1,
        "probe": "github_scm_live_readonly",
        "ok": True,
        "repository": repository,
        "pull_request_number": pull_request_number,
        "pull_request": {
            "state": pull_request.get("state"),
            "merged": pull_request.get("merged"),
            "draft": pull_request.get("draft"),
            "head_sha": head_sha,
            "base_branch": pull_request.get("base_branch"),
        },
        "ci": {
            "status": ci_status,
            "commit_status": ci.get("commit_status"),
            "check_runs": _safe_check_runs(ci.get("check_runs")),
            "checks_complete": ci.get("checks_complete", False),
        },
        "review": {
            "status": review_status,
            "review_count": review.get("review_count", 0),
            "states": [
                state[:40] for state in review.get("states", [])
                if isinstance(state, str)
            ][:100],
            "reviews_complete": review.get("reviews_complete", False),
        },
        "assessment": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "ci_aggregation_probe": ci_aggregation_probe,
    }


def main() -> int:
    try:
        runtime = create_github_scm_runtime()
        if runtime is None or runtime.pull_request_number is None:
            raise RuntimeError("host GitHub SCM configuration is unavailable")
        result = observe(
            runtime.service,
            runtime.repository,
            runtime.pull_request_number,
            ci_probe_sha=os.environ.get("AI_TEAM_GITHUB_CI_PROBE_SHA") or None,
        )
    except Exception as exc:  # Never print a remote message or credential.
        result = {
            "schema_version": 1,
            "probe": "github_scm_live_readonly",
            "ok": False,
            "error_type": type(exc).__name__,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # A blocked PR is a successful observation, not a failed API integration.
    # The optional pinned commit probe must independently aggregate Check Runs
    # successfully; it catches an empty legacy-status collection masking green CI.
    ci_probe = result.get("ci_aggregation_probe")
    if isinstance(ci_probe, dict) and ci_probe.get("status") != "success":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
