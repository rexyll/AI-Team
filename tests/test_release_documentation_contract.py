from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EXAMPLES_README = ROOT / "examples" / "README.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required document: {path}"
    return path.read_text(encoding="utf-8-sig")


def test_all_release_documents_exist() -> None:
    for name in (
        DOCS / "setup.md",
        DOCS / "production_configuration.md",
        DOCS / "release_readiness.md",
        EXAMPLES_README,
    ):
        assert name.is_file()


def test_release_readiness_checklist_links_evidence() -> None:
    content = _read(DOCS / "release_readiness.md")

    for token in (
        "pytest -q",
        "tests/test_release_readiness_smoke_contract.py",
        "tests/test_security_contract.py",
        "tests/test_production_configuration_contract.py",
        "tests/test_developer_llm_injection_contract.py",
        "AGNES_API_KEY",
        "Python 3.14",
        "os.replace()",
        "commit SHA",
    ):
        assert token in content, f"release checklist must reference: {token}"


def test_release_documents_cross_reference_each_other() -> None:
    setup = _read(DOCS / "setup.md")
    production = _read(DOCS / "production_configuration.md")

    assert "docs/production_configuration.md" in setup
    # The production checklist must point back to the entry documentation.
    assert "DevPlan" in production or "setup" in production.lower()
