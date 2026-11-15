from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OSV_PYPI_MODIFIED_URL = (
    "https://osv-vulnerabilities.storage.googleapis.com/PyPI/modified_id.csv"
)
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{vulnerability_id}"


def _iso_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_osv_freshness(
    *,
    source_last_modified: datetime,
    latest_advisory_id: str,
    latest_advisory_modified: datetime,
    api_record_modified: datetime,
    now: datetime | None = None,
    max_age: timedelta = timedelta(hours=24),
) -> tuple[dict[str, Any], list[str]]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_last_modified = source_last_modified.astimezone(timezone.utc)
    latest_advisory_modified = latest_advisory_modified.astimezone(timezone.utc)
    api_record_modified = api_record_modified.astimezone(timezone.utc)
    problems: list[str] = []

    if not latest_advisory_id.strip():
        problems.append("OSV PyPI modified_id.csv has no latest advisory ID")
    if source_last_modified > checked_at + timedelta(minutes=5):
        problems.append("OSV PyPI export Last-Modified is in the future")
    if latest_advisory_modified > checked_at + timedelta(minutes=5):
        problems.append("latest PyPI advisory modified timestamp is in the future")
    if api_record_modified > checked_at + timedelta(minutes=5):
        problems.append("OSV API advisory modified timestamp is in the future")
    if api_record_modified < latest_advisory_modified:
        problems.append("OSV API does not contain the latest PyPI advisory revision")

    age = checked_at - source_last_modified
    if age > max_age:
        problems.append(
            f"OSV PyPI export is stale: age {age.total_seconds() / 3600:.2f}h "
            f"exceeds {max_age.total_seconds() / 3600:.2f}h"
        )

    result = {
        "status": "stale" if problems else "fresh",
        "ecosystem": "PyPI",
        "source_url": OSV_PYPI_MODIFIED_URL,
        "source_last_modified": source_last_modified.isoformat(),
        "latest_advisory_id": latest_advisory_id,
        "latest_advisory_modified": latest_advisory_modified.isoformat(),
        "api_record_modified": api_record_modified.isoformat(),
        "checked_at": checked_at.isoformat(),
        "age_seconds": max(0.0, age.total_seconds()),
        "max_age_seconds": max_age.total_seconds(),
        "problems": problems,
    }
    return result, problems


def _request(url: str, *, method: str, timeout: float) -> tuple[dict[str, str], bytes]:
    request = Request(url, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ValueError(f"HTTP {status} from {url}")
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read() if method == "GET" else b""
            return headers, body
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ValueError(f"OSV freshness endpoint unavailable: {url}: {exc}") from exc


def fetch_osv_freshness(
    *,
    timeout: float = 15.0,
    now: datetime | None = None,
    max_age: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    headers, _ = _request(OSV_PYPI_MODIFIED_URL, method="HEAD", timeout=timeout)
    last_modified_header = headers.get("last-modified")
    if not last_modified_header:
        raise ValueError("OSV PyPI export is missing its Last-Modified header")
    source_last_modified = parsedate_to_datetime(last_modified_header).astimezone(
        timezone.utc
    )

    _, body = _request(OSV_PYPI_MODIFIED_URL, method="GET", timeout=timeout)
    first_line = next(
        (line.strip() for line in body.decode("utf-8").splitlines() if line.strip()),
        "",
    )
    fields = [field.strip() for field in first_line.split(",", 1)]
    if len(fields) != 2 or not fields[1]:
        raise ValueError("OSV PyPI modified_id.csv has no valid latest record")
    latest_advisory_modified = _iso_timestamp(fields[0], "latest advisory timestamp")
    latest_advisory_id = fields[1]

    api_headers, api_body = _request(
        OSV_VULN_URL.format(vulnerability_id=latest_advisory_id),
        method="GET",
        timeout=timeout,
    )
    del api_headers
    api_record = json.loads(api_body.decode("utf-8"))
    api_record_modified = _iso_timestamp(
        api_record.get("modified", ""),
        "OSV API advisory modified timestamp",
    )
    result, problems = evaluate_osv_freshness(
        source_last_modified=source_last_modified,
        latest_advisory_id=latest_advisory_id,
        latest_advisory_modified=latest_advisory_modified,
        api_record_modified=api_record_modified,
        now=now,
        max_age=max_age,
    )
    result["source_etag"] = headers.get("etag")
    result["source_content_length"] = headers.get("content-length")
    if problems:
        result["status"] = "stale"
    return result


def build_scan_metadata(
    *,
    database: dict[str, Any],
    lock_path: Path,
    commit: str,
    pip_audit_version: str,
    trivy_version: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not lock_path.is_file():
        raise ValueError(f"production lock file does not exist: {lock_path}")
    if not commit.strip() or not pip_audit_version.strip() or not trivy_version.strip():
        raise ValueError("commit and scanner versions are required")
    return {
        "schema_version": 1,
        "scanned_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "commit": commit,
        "scan_target": "production-linux-py314",
        "lock_file": {
            "path": lock_path.as_posix(),
            "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        },
        "scanners": {
            "vulnerability": {"name": "pip-audit", "version": pip_audit_version.strip()},
            "license": {"name": "trivy", "version": trivy_version.strip()},
        },
        "vulnerability_database": database,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock-file", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--pip-audit-version", required=True)
    parser.add_argument("--trivy-version", required=True)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path, default=Path("dependency-scan-metadata.json"))
    args = parser.parse_args(argv)

    try:
        database = fetch_osv_freshness(
            timeout=args.timeout_seconds,
            max_age=timedelta(hours=args.max_age_hours),
        )
        evidence = build_scan_metadata(
            database=database,
            lock_path=args.lock_file,
            commit=args.commit,
            pip_audit_version=args.pip_audit_version,
            trivy_version=args.trivy_version,
        )
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: OSV database freshness/evidence unavailable: {exc}", file=sys.stderr)
        return 2

    print(
        "OSV PyPI database freshness: "
        f"{database['status']} "
        f"(source_last_modified={database['source_last_modified']}, "
        f"latest_advisory={database['latest_advisory_id']})"
    )
    if database["problems"]:
        for problem in database["problems"]:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"PASS: dependency scan metadata written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
