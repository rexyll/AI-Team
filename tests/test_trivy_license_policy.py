from pathlib import Path

from tools.check_trivy_license_policy import evaluate_license_report, _read_lock


POLICY = {
    "allowed_classifications": ["NOTICE", "PERMISSIVE", "UNENCUMBERED"],
    "blocked_classifications": ["UNKNOWN", "RECIPROCAL", "RESTRICTED", "FORBIDDEN"],
    "unknown_license_policy": "deny",
    "exceptions": [],
    "license_classification_overrides": {
        "PSF-2.0": {
            "classification": "NOTICE",
            "source": "https://spdx.org/licenses/PSF-2.0.html",
            "rationale": "SPDX-listed PSF 2.0 grants royalty-free redistribution and derivative works with retention of the PSF license and copyright notice.",
        }
    },
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
    assert not any("PSF-2.0" in problem for problem in result["problems"])
    assert any("RECIPROCAL" in problem for problem in result["problems"])


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


def test_license_policy_applies_only_exact_approved_package_version_and_expression(tmp_path: Path):
    from datetime import date

    lock = tmp_path / "requirements.lock"
    lock.write_text("tqdm==4.70.1\nother-lib==2.0.0\n", encoding="utf-8")
    packages = [
        {"Name": "tqdm", "Version": "4.70.1", "Licenses": ["MPL-2.0 AND MIT"]},
        {"Name": "other-lib", "Version": "2.0.0", "Licenses": ["MIT"]},
    ]
    findings = [{
        "PkgName": "tqdm",
        "Name": "MPL-2.0 AND MIT",
        "Category": "reciprocal",
        "Severity": "MEDIUM",
    }]
    policy = {
        **POLICY,
        "exceptions": [{
            "package": "tqdm",
            "version": "4.70.1",
            "license": "MPL-2.0 AND MIT",
            "classification": "RECIPROCAL",
            "approved_by": "repository owner (rexyll)",
            "approved_at": "2026-11-15",
            "expires_on": "2027-02-13",
            "rationale": "Narrowly approved for the current OpenAI SDK transitive dependency while retaining MPL and MIT obligations.",
            "obligations": [
                "Retain upstream copyright and license notices.",
                "Provide MPL-2.0 and MIT license texts or authoritative URLs on redistribution.",
                "If MPL-covered files are modified and distributed, provide their corresponding source under MPL-2.0.",
                "Review before 2027-02-13.",
            ],
        }],
    }
    report = _report(
        packages=packages,
        findings=findings,
    )

    result = evaluate_license_report(
        report, _read_lock(lock), policy, as_of=date(2026, 11, 15)
    )

    assert result["status"] == "passed"
    assert result["problems"] == []
    assert result["exceptions_applied"] == [{
        "package": "tqdm",
        "version": "4.70.1",
        "license": "MPL-2.0 AND MIT",
        "expires_on": "2027-02-13",
        "approved_by": "repository owner (rexyll)",
    }]


def test_license_exception_does_not_match_another_version_or_license_expression(tmp_path: Path):
    from datetime import date

    lock = tmp_path / "requirements.lock"
    lock.write_text("tqdm==4.70.2\nother-lib==2.0.0\n", encoding="utf-8")
    packages = [
        {"Name": "tqdm", "Version": "4.70.2", "Licenses": ["MPL-2.0 AND MIT"]},
        {"Name": "other-lib", "Version": "2.0.0", "Licenses": ["MIT"]},
    ]
    policy = {
        **POLICY,
        "exceptions": [{
            "package": "tqdm",
            "version": "4.70.2",
            "license": "MPL-2.0",
            "classification": "RECIPROCAL",
            "approved_by": "repository owner (rexyll)",
            "approved_at": "2026-11-15",
            "expires_on": "2027-02-13",
            "rationale": "Test-only narrow exception.",
            "obligations": ["Retain notices."],
        }],
    }
    report = _report(packages=packages, findings=[{
        "PkgName": "tqdm",
        "Name": "MPL-2.0 AND MIT",
        "Category": "reciprocal",
        "Severity": "MEDIUM",
    }])

    result = evaluate_license_report(
        report, _read_lock(lock), policy, as_of=date(2026, 11, 15)
    )

    assert result["status"] == "failed"
    assert result["exceptions_applied"] == []
    assert any("blocked" in problem for problem in result["problems"])


def test_license_exception_expiry_fails_closed(tmp_path: Path):
    from datetime import date

    lock = tmp_path / "requirements.lock"
    lock.write_text("tqdm==4.70.1\nother-lib==2.0.0\n", encoding="utf-8")
    policy = {
        **POLICY,
        "exceptions": [{
            "package": "tqdm",
            "version": "4.70.1",
            "license": "MPL-2.0 AND MIT",
            "classification": "RECIPROCAL",
            "approved_by": "repository owner (rexyll)",
            "approved_at": "2026-11-15",
            "expires_on": "2026-11-14",
            "rationale": "Expired exception test.",
            "obligations": ["Retain notices."],
        }],
    }
    result = evaluate_license_report(
        _report(), _read_lock(lock), policy, as_of=date(2026, 11, 15)
    )

    assert result["status"] == "failed"
    assert any("expired" in problem for problem in result["problems"])


def test_license_exception_requires_scanner_classification_to_match_policy(tmp_path: Path):
    from datetime import date

    lock = tmp_path / "requirements.lock"
    lock.write_text("tqdm==4.70.1\nother-lib==2.0.0\n", encoding="utf-8")
    policy = {
        **POLICY,
        "exceptions": [{
            "package": "tqdm",
            "version": "4.70.1",
            "license": "MPL-2.0 AND MIT",
            "classification": "RESTRICTED",
            "approved_by": "repository owner (rexyll)",
            "approved_at": "2026-11-15",
            "expires_on": "2027-02-13",
            "rationale": "Mismatch test.",
            "obligations": ["Retain notices."],
        }],
    }
    packages = [
        {"Name": "tqdm", "Version": "4.70.1", "Licenses": ["MPL-2.0 AND MIT"]},
        {"Name": "other-lib", "Version": "2.0.0", "Licenses": ["MIT"]},
    ]
    report = _report(packages=packages, findings=[{
        "PkgName": "tqdm",
        "Name": "MPL-2.0 AND MIT",
        "Category": "reciprocal",
        "Severity": "MEDIUM",
    }])

    result = evaluate_license_report(
        report, _read_lock(lock), policy, as_of=date(2026, 11, 15)
    )

    assert result["status"] == "failed"
    assert result["exceptions_applied"] == []
    assert any("blocked" in problem for problem in result["problems"])
    assert any("did not match" in problem for problem in result["problems"])
