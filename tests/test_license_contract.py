from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LICENSE = ROOT / "LICENSE"
README = ROOT / "README.md"
THIRD_PARTY_NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"


def test_project_license_contains_both_complete_polyform_license_paths() -> None:
    license_text = LICENSE.read_text(encoding="utf-8")

    assert "# PolyForm Noncommercial License 1.0.0" in license_text
    assert "https://polyformproject.org/licenses/noncommercial/1.0.0" in license_text
    assert "# PolyForm Small Business License 1.0.0" in license_text
    assert "https://polyformproject.org/licenses/small-business/1.0.0" in license_text

    # Both grants must retain their own complete standard-license structure.
    for section in (
        "Acceptance",
        "Copyright License",
        "Distribution License",
        "Notices",
        "Changes and New Works License",
        "Patent License",
        "Fair Use",
        "No Other Rights",
        "Patent Defense",
        "Violations",
        "No Liability",
        "Definitions",
    ):
        assert license_text.count(f"## {section}") == 2, (
            f"both PolyForm license texts must contain the {section!r} section"
        )

    assert "Any noncommercial purpose is a permitted purpose." in license_text
    assert "Personal use for research, experiment, and testing" in license_text
    assert "fewer than 100 total" in license_text
    assert "less than 1,000,000 USD (2019) total revenue" in license_text
    assert "consumer price index for all urban consumers" in license_text


def test_readme_and_third_party_notices_preserve_separate_license_boundaries() -> None:
    readme = README.read_text(encoding="utf-8")
    notices = THIRD_PARTY_NOTICES.read_text(encoding="utf-8")

    assert "PolyForm Noncommercial License 1.0.0" in readme
    assert "PolyForm Small Business License 1.0.0" in readme
    assert "Other commercial use" in readme
    assert "tqdm 4.70.1" in notices
    assert "MPL-2.0 AND MIT" in notices
    assert "project license does not replace or relicense third-party software" in notices
