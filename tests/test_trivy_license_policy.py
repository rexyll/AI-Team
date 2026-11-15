from pathlib import Path

from tools.check_trivy_license_policy import evaluate_license_report, _read_lock


POLICY = {
    "allowed_classifications": ["NOTICE", "PERMISSIVE", "UNENCUMBERED"],
    "blocked_classifications": ["UNKNOWN", "RECIPROCAL", "RESTRICTED", "FORBIDDEN"],
    "unknown_license_policy": "deny",
    "exceptions": [],
}


def _report(*, packages=None, findings=None):
    return {
        "SchemaVersion": 2,
        "Trivy": {"Version": "0.76.2"},
        "Results": [
            {
                "Target": "requirements.txt",
                "Class": "lang-pkgs",
                "Type": "pip",
                "Packages": packages if packages is not None else [
                    {"Name": "sample-lib", "Version": "1.0.0", "Licenses": ["MIT"]},
                    {"Name": "other-lib", "Version": "2.0.0", "Licenses": ["Apache-2.0"]},
                ],
            },
            {
                "Target": "requirements.txt",
                "Class": "license",
                "Licenses": findings if findings is not None else [],
            },
        ],
    }


def test_license_policy_accepts_complete_permissive_production_inventory(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("sample_lib==1.0.0\nother-lib==2.0.0\n", encoding="utf-8")

    result = evaluate_license_report(_report(), _read_lock(lock), POLICY)

    assert result["status"] == "passed"
    assert result["packages_expected"] == 2
    assert result["packages_observed"] == 2
    assert result["problems"] == []


def test_license_policy_blocks_reciprocal_and_unknown_classifications(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("sample-lib==1.0.0\nother-lib==2.0.0\n", encoding="utf-8")
    findings = [
        {
            "PkgName": "sample-lib",
            "Name": "MPL-2.0 AND MIT",
            "Category": "reciprocal",
            "Severity": "MEDIUM",
        },
        {
            "PkgName": "other-lib",
            "Name": "PSF-2.0",
            "Category": "unknown",
            "Severity": "UNKNOWN",
        },
    ]

    result = evaluate_license_report(
        _report(findings=findings), _read_lock(lock), POLICY
    )

    assert result["status"] == "failed"
    assert any("RECIPROCAL" in problem for problem in result["problems"])
    assert any("UNKNOWN" in problem for problem in result["problems"])


def test_license_policy_rejects_missing_license_metadata_and_inventory_mismatch(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("sample-lib==1.0.0\nother-lib==2.0.0\n", encoding="utf-8")
    packages = [
        {"Name": "sample-lib", "Version": "1.0.0", "Licenses": ["MIT"]},
        {"Name": "other-lib", "Version": "2.0.0", "Licenses": []},
    ]

    result = evaluate_license_report(
        _report(packages=packages), _read_lock(lock), POLICY
    )

    assert result["status"] == "failed"
    assert any("no declared license metadata" in problem for problem in result["problems"])


def test_license_policy_rejects_unrecognized_categories_and_exceptions(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("sample-lib==1.0.0\nother-lib==2.0.0\n", encoding="utf-8")
    policy = {**POLICY, "exceptions": [{"package": "sample-lib"}]}
    findings = [
        {
            "PkgName": "sample-lib",
            "Name": "Custom-License",
            "Category": "unclassified",
            "Severity": "UNKNOWN",
        }
    ]

    result = evaluate_license_report(
        _report(findings=findings), _read_lock(lock), policy
    )

    assert result["status"] == "failed"
    assert any("exceptions require" in problem for problem in result["problems"])
    assert any("unrecognized category" in problem for problem in result["problems"])


def test_lock_parser_rejects_unpinned_or_unexpanded_requirements(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("-r base.txt\nsample-lib>=1.0\n", encoding="utf-8")

    try:
        _read_lock(lock)
    except ValueError as exc:
        assert "unsupported lock requirement" in str(exc)
    else:
        raise AssertionError("unexpanded lock requirements must be rejected")
