"""Post-delivery monitoring contract and heartbeat contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import main as main_module
from runtime.delivery_manifest import write_delivery_manifest
from runtime.monitoring import (
    HEALTH_CONTRACT_FILENAME,
    HEALTH_STATUS_FILENAME,
    MONITORING_DIR,
    build_monitoring_contract,
    render_monitoring_doc,
    run_health_checks,
    write_monitoring_contract,
)

_NOW = datetime(2026, 11, 4, 8, 0, 0, tzinfo=timezone.utc)


def _release(version: str = "0.1.0") -> dict:
    return {
        "status": "released",
        "version": version,
        "tag": f"v{version}",
        "commit": "a" * 40,
    }


def _write_release_log(root: Path, *, version: str = "0.1.0") -> None:
    entry = {**_release(version), "project": "todo", "created_at": "2026-11-03T00:00:00Z"}
    (root / "release_log.json").write_text(
        json.dumps({"releases": [entry]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _make_deliverable(tmp_path: Path, *, released: bool = True) -> Path:
    root = tmp_path / "delivered"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "test_app.py").write_text(
        "import app\n\ndef test_ok():\n    assert app.VALUE == 1\n", encoding="utf-8"
    )
    if released:
        _write_release_log(root)
    write_monitoring_contract(
        root, project="todo", release=_release() if released else None
    )
    write_delivery_manifest(root, project="todo")
    return root


def test_build_monitoring_contract_is_deterministic_and_honest():
    contract = build_monitoring_contract(
        project="todo",
        deliverable_root="delivered",
        release=_release(),
        created_at=_NOW,
    )

    assert contract["schema_version"] == 1
    assert contract["release"]["version"] == "0.1.0"
    assert [probe["id"] for probe in contract["probes"]] == [
        "release_anchor",
        "manifest_integrity",
        "smoke_suite",
    ]
    assert "未接入云监控" in contract["limitations"]
    assert "--monitor-check delivered" in contract["heartbeat"]["command"]
    doc = render_monitoring_doc(contract)
    assert "MONITORING" in doc
    assert "缺陷回流" in doc
    assert "v0.1.0" in doc


def test_write_monitoring_contract_places_artifacts_in_deliverable(tmp_path: Path):
    root = tmp_path / "delivered"
    root.mkdir()

    outcome = write_monitoring_contract(
        root, project="todo", release=_release(), created_at=_NOW
    )

    contract_path = root / MONITORING_DIR / HEALTH_CONTRACT_FILENAME
    assert contract_path.is_file()
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    assert payload["release"]["tag"] == "v0.1.0"
    assert (root / "MONITORING.md").is_file()
    assert outcome["status"] == "configured"
    assert outcome["release"] == "0.1.0"


def test_health_checks_are_healthy_for_an_intact_deliverable(tmp_path: Path):
    root = _make_deliverable(tmp_path)

    report = run_health_checks(root, now=_NOW)

    assert report["status"] == "healthy"
    statuses = {probe["id"]: probe["status"] for probe in report["probes"]}
    assert statuses == {
        "release_anchor": "pass",
        "manifest_integrity": "pass",
        "smoke_suite": "pass",
    }
    status_file = root / MONITORING_DIR / HEALTH_STATUS_FILENAME
    assert status_file.is_file()
    assert json.loads(status_file.read_text(encoding="utf-8"))["status"] == "healthy"


def test_tampered_deliverable_fails_manifest_integrity(tmp_path: Path):
    root = _make_deliverable(tmp_path)
    (root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    report = run_health_checks(root, run_smoke=False, now=_NOW)

    assert report["status"] == "failed"
    manifest = next(p for p in report["probes"] if p["id"] == "manifest_integrity")
    assert manifest["status"] == "fail"
    assert "app.py" in manifest["mismatched"]


def test_missing_release_log_degrades_but_does_not_fake_health(tmp_path: Path):
    root = _make_deliverable(tmp_path, released=False)
    (root / "release_log.json").unlink(missing_ok=True)

    report = run_health_checks(root, run_smoke=False, now=_NOW)

    assert report["status"] == "degraded"
    anchor = next(p for p in report["probes"] if p["id"] == "release_anchor")
    assert anchor["status"] == "unavailable"
    assert "没有发布记录" in anchor["reason"]


def test_health_checks_reject_missing_directory(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        run_health_checks(tmp_path / "missing", run_smoke=False)


def test_monitor_check_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    healthy = _make_deliverable(tmp_path)
    assert main_module.run_monitor_check(str(healthy)) == 0
    assert "healthy" in capsys.readouterr().out.lower()

    degraded_root = tmp_path / "degraded"
    degraded_root.mkdir()
    (degraded_root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_monitoring_contract(degraded_root, project="todo", release=None)
    write_delivery_manifest(degraded_root, project="todo")
    assert main_module.run_monitor_check(str(degraded_root)) == 1


def test_monitor_check_json_output_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _make_deliverable(tmp_path)

    assert main_module.run_monitor_check(str(root), output="json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "healthy"
    assert payload["deliverable_root"] == str(root)
