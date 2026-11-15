from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

from tools.check_osv_db_freshness import (
    build_scan_metadata,
    evaluate_osv_freshness,
)


NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _fresh_values():
    return {
        "source_last_modified": datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc),
        "latest_advisory_id": "PYSEC-2026-123",
        "latest_advisory_modified": datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc),
        "api_record_modified": datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc),
    }


def test_osv_database_is_fresh_when_export_and_api_are_current():
    result, problems = evaluate_osv_freshness(**_fresh_values(), now=NOW)

    assert problems == []
    assert result["status"] == "fresh"
    assert result["ecosystem"] == "PyPI"
    assert result["latest_advisory_id"] == "PYSEC-2026-123"


def test_osv_database_export_older_than_freshness_window_is_rejected():
    values = _fresh_values()
    values["source_last_modified"] = datetime(
        2026, 11, 13, 10, 0, tzinfo=timezone.utc
    )
    result, problems = evaluate_osv_freshness(**values, now=NOW)

    assert result["status"] == "stale"
    assert any("OSV PyPI export is stale" in problem for problem in problems)


def test_osv_api_must_contain_the_latest_exported_advisory_revision():
    values = _fresh_values()
    values["api_record_modified"] = datetime(
        2026, 11, 15, 8, 0, tzinfo=timezone.utc
    )
    result, problems = evaluate_osv_freshness(**values, now=NOW)

    assert result["status"] == "stale"
    assert any("does not contain the latest" in problem for problem in problems)


def test_missing_advisory_id_and_future_timestamps_fail_closed():
    values = _fresh_values()
    values["latest_advisory_id"] = ""
    values["source_last_modified"] = datetime(
        2026, 11, 15, 13, 0, tzinfo=timezone.utc
    )
    result, problems = evaluate_osv_freshness(**values, now=NOW)

    assert result["status"] == "stale"
    assert any("no latest advisory ID" in problem for problem in problems)
    assert any("in the future" in problem for problem in problems)


def test_scan_metadata_binds_lock_and_both_scanner_versions(tmp_path: Path):
    lock = tmp_path / "requirements-linux-py314.lock"
    lock.write_text("sample==1.0.0\n", encoding="utf-8")
    database, problems = evaluate_osv_freshness(**_fresh_values(), now=NOW)

    evidence = build_scan_metadata(
        database=database,
        lock_path=lock,
        commit="abc123",
        pip_audit_version="pip-audit 2.10.1",
        trivy_version="Version: 0.76.2",
        now=NOW,
    )

    assert problems == []
    assert evidence["scanners"]["vulnerability"]["version"] == "pip-audit 2.10.1"
    assert evidence["scanners"]["license"]["version"] == "Version: 0.76.2"
    assert evidence["lock_file"]["sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()
