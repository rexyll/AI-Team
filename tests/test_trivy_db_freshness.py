from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from tools.check_trivy_db_freshness import (
    build_scan_metadata,
    evaluate_database_metadata,
)


NOW = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)


def _database(**overrides):
    data = {
        "Version": 2,
        "UpdatedAt": "2026-11-15T08:00:00Z",
        "NextUpdate": "2026-11-16T08:00:00Z",
        "DownloadedAt": "2026-11-15T08:01:00Z",
    }
    data.update(overrides)
    return data


def test_fresh_trivy_database_is_accepted():
    result, problems = evaluate_database_metadata(_database(), now=NOW)

    assert problems == []
    assert result["status"] == "fresh"
    assert result["version"] == 2


def test_stale_trivy_database_is_rejected():
    result, problems = evaluate_database_metadata(
        _database(UpdatedAt="2026-11-13T08:00:00Z", NextUpdate="2026-11-14T08:00:00Z"),
        now=NOW,
    )

    assert result["status"] == "stale"
    assert any("exceeds 24.00h" in problem for problem in problems)
    assert any("passed NextUpdate" in problem for problem in problems)


def test_missing_or_timezone_free_database_metadata_fails_closed():
    missing, missing_problems = evaluate_database_metadata(
        {"Version": 2}, now=NOW
    )
    naive, naive_problems = evaluate_database_metadata(
        _database(UpdatedAt="2026-11-15T08:00:00"), now=NOW
    )

    assert missing["status"] == "unknown"
    assert missing_problems
    assert naive["status"] == "unknown"
    assert any("must include a timezone" in problem for problem in naive_problems)


def test_future_or_inconsistent_database_timestamps_fail_closed():
    result, problems = evaluate_database_metadata(
        _database(
            UpdatedAt="2026-11-15T11:00:00Z",
            NextUpdate="2026-11-15T10:30:00Z",
            DownloadedAt="2026-11-15T09:00:00Z",
        ),
        now=NOW,
    )

    assert result["status"] == "stale"
    assert any("in the future" in problem for problem in problems)
    assert any("predates UpdatedAt" in problem for problem in problems)
    assert any("NextUpdate must be later" in problem for problem in problems)


def test_scan_metadata_binds_lock_digest_scanner_and_database(tmp_path: Path):
    lock = tmp_path / "requirements-linux-py314.lock"
    lock.write_text("sample==1.0.0\n", encoding="utf-8")
    database, problems = evaluate_database_metadata(_database(), now=NOW)

    evidence = build_scan_metadata(
        database=database,
        lock_path=lock,
        scanner_version="Version: 0.76.2",
        commit="abc123",
        scan_target="production-linux-py314",
        now=NOW,
    )

    assert problems == []
    assert evidence["scanner"] == {"name": "trivy", "version": "Version: 0.76.2"}
    assert evidence["lock_file"]["sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert evidence["vulnerability_database"]["status"] == "fresh"
