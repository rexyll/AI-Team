import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "dependency-security.yml"
POLICY = ROOT / "config" / "dependency_license_policy.json"


def test_dependency_security_scan_uses_immutable_scanners_and_block_egress():
    workflow = WORKFLOW.read_text(encoding="utf-8-sig")

    assert "workflow_dispatch:" in workflow
    assert "branches: [main]" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "aquasecurity/setup-trivy@a0e5e8d8f5936915ac0292775f38a64d6fabe7a7" in workflow
    assert "version: v0.76.2" in workflow
    assert "step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1" in workflow
    assert "egress-policy: block" in workflow
    assert "allowed-endpoints: >" in workflow
    assert "disable-telemetry: true" in workflow
    assert "api.osv.dev:443" in workflow
    assert "osv-vulnerabilities.storage.googleapis.com:443" in workflow
    assert "actions-results-receiver-production.githubapp.com:443" in workflow
    assert "results-receiver.actions.githubusercontent.com:443" in workflow
    assert "pipelines.actions.githubusercontent.com:443" in workflow


def test_dependency_security_scans_only_production_lock_and_fails_closed():
    workflow = WORKFLOW.read_text(encoding="utf-8-sig")

    prepare_start = workflow.index("  prepare-scan-input:")
    scan_start = workflow.index("  scan-production-dependencies:")
    prepare = workflow[prepare_start:scan_start]
    scan = workflow[scan_start:]

    assert "actions/checkout@v4" in prepare
    assert "requirements-linux-py314.lock" in prepare
    assert "requirements-dev-linux-py314.lock" in prepare
    assert "--require-hashes" in prepare
    assert "aquasecurity/setup-trivy@" in prepare
    assert "scan-tools" in prepare
    assert "Package production scan input" in prepare

    assert "Restrict scanner network egress" in scan
    assert scan.index("Restrict scanner network egress") < scan.index("Download prepared scan input")
    assert "actions/checkout@v4" not in scan
    assert "requirements-dev-linux-py314.lock" not in scan
    assert "python -m pip_audit" in scan
    assert "--vulnerability-service osv" in scan
    assert "--no-deps" in scan
    assert "--disable-pip" in scan
    assert "--require-hashes" in scan
    assert "--strict" in scan
    assert "--scanners license" in scan
    assert "--exit-code 0" in scan
    assert "check_osv_db_freshness.py" in scan
    assert "check_trivy_license_policy.py" in scan
    assert "--max-age-hours 24" in scan
    assert "mirror.gcr.io" not in scan
    assert "ghcr.io" not in scan
    assert "pypi.org" not in scan
    assert "if: always()" in scan
    assert "retention-days: 30" in scan


def test_license_policy_denies_unknown_and_requires_explicit_exceptions():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["scope"] == "production-linux-py314"
    assert set(policy["allowed_classifications"]) == {
        "NOTICE",
        "PERMISSIVE",
        "UNENCUMBERED",
    }
    assert set(policy["blocked_classifications"]) == {
        "UNKNOWN",
        "RECIPROCAL",
        "RESTRICTED",
        "FORBIDDEN",
    }
    assert policy["unknown_license_policy"] == "deny"
    assert policy["scanner_unavailable_policy"] == "deny"
    assert policy["stale_database_policy"] == "deny"
    assert policy["exceptions"] == []
