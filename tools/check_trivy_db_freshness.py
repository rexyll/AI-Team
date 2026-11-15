from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Trivy DB metadata field {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Trivy DB metadata field {field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Trivy DB metadata field {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_database_metadata(
    metadata: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age: timedelta = timedelta(hours=24),
) -> tuple[dict[str, Any], list[str]]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    problems: list[str] = []
    try:
        version = metadata.get("Version")
        if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
            raise ValueError("Trivy DB metadata Version must be a positive integer")
        updated_at = _timestamp(metadata.get("UpdatedAt"), "UpdatedAt")
        next_update = _timestamp(metadata.get("NextUpdate"), "NextUpdate")
        downloaded_at = _timestamp(metadata.get("DownloadedAt"), "DownloadedAt")
    except ValueError as exc:
        return {
            "status": "unknown",
            "checked_at": checked_at.isoformat(),
            "problems": [str(exc)],
        }, [str(exc)]

    if updated_at > checked_at + timedelta(minutes=5):
        problems.append("Trivy DB UpdatedAt is in the future")
    if downloaded_at > checked_at + timedelta(minutes=5):
        problems.append("Trivy DB DownloadedAt is in the future")
    if downloaded_at < updated_at:
        problems.append("Trivy DB DownloadedAt predates UpdatedAt")
    if next_update <= updated_at:
        problems.append("Trivy DB NextUpdate must be later than UpdatedAt")
    age = checked_at - updated_at
    if age > max_age:
        problems.append(
            f"Trivy DB is stale: age {age.total_seconds() / 3600:.2f}h "
            f"exceeds {max_age.total_seconds() / 3600:.2f}h"
        )
    if checked_at >= next_update:
        problems.append("Trivy DB has passed NextUpdate")

    result = {
        "status": "stale" if problems else "fresh",
        "version": version,
        "updated_at": updated_at.isoformat(),
        "next_update": next_update.isoformat(),
        "downloaded_at": downloaded_at.isoformat(),
        "checked_at": checked_at.isoformat(),
        "age_seconds": max(0.0, age.total_seconds()),
        "max_age_seconds": max_age.total_seconds(),
        "problems": problems,
    }
    return result, problems


def build_scan_metadata(
    *,
    database: dict[str, Any],
    lock_path: Path,
    scanner_version: str,
    commit: str,
    scan_target: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not lock_path.is_file():
        raise ValueError(f"scan lock file does not exist: {lock_path}")
    if not scanner_version.strip():
        raise ValueError("scanner version is required")
    if not commit.strip():
        raise ValueError("commit SHA is required")
    return {
        "schema_version": 1,
        "scanned_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "commit": commit,
        "scanner": {"name": "trivy", "version": scanner_version.strip()},
        "scan_target": scan_target,
        "lock_file": {
            "path": lock_path.as_posix(),
            "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        },
        "vulnerability_database": database,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--lock-file", required=True, type=Path)
    parser.add_argument("--scanner-version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--scan-target", required=True)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--output", type=Path, default=Path("dependency-scan-metadata.json"))
    args = parser.parse_args(argv)

    try:
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("Trivy DB metadata must be a JSON object")
        database, problems = evaluate_database_metadata(
            metadata,
            max_age=timedelta(hours=args.max_age_hours),
        )
        evidence = build_scan_metadata(
            database=database,
            lock_path=args.lock_file,
            scanner_version=args.scanner_version,
            commit=args.commit,
            scan_target=args.scan_target,
        )
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: dependency scan evidence unavailable: {exc}", file=sys.stderr)
        return 2

    print(
        "Trivy DB freshness: "
        f"{database.get('status')} "
        f"(updated_at={database.get('updated_at')}, "
        f"next_update={database.get('next_update')})"
    )
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"PASS: dependency scan metadata written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
