from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SETUP = ROOT / "docs" / "setup.md"


def test_setup_guide_exists_and_covers_canonical_runtime_entry_points() -> None:
    assert SETUP.is_file()
    content = SETUP.read_text(encoding="utf-8-sig")

    required_sections = (
        "# AI-Team Setup Guide",
        "## 2. Create the virtual environment",
        "## 4. Run the project",
        "## 5. Run tests",
        "## 6. Agent configuration",
        "## 7. LLM provider and mock execution",
        "## 8. Tools, permissions, and workspace sandbox",
        "## 9. Persistence and recovery",
        "## 10. Canonical runtime lifecycle",
    )
    for section in required_sections:
        assert section in content


def test_setup_guide_uses_current_cli_and_query_contracts() -> None:
    content = SETUP.read_text(encoding="utf-8-sig")

    assert 'python main.py "Build a small personal expense tracker"' in content
    assert "pytest -q" in content
    assert "create_agent_router" in content
    assert "AgentConfig" in content
    assert "WorkflowEventPersistenceAdapter" in content
    assert "WorkflowEventQueryService.from_persistence" in content
    assert "WorkflowEventQueryService.from_persisted_project" in content
    assert "task_started" in content
    assert "developer_completed" in content
    assert "tester_skipped" in content
    assert "review_started" in content
    assert "reviewer_approved" in content


def test_readme_points_to_setup_and_devplan() -> None:
    content = README.read_text(encoding="utf-8-sig")

    assert "DevPlan.md" in content
    assert "docs/setup.md" in content
    assert "pytest -q" in content
    assert "python main.py" in content
