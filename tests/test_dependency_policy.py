from pathlib import Path

import pytest

from security.dependency_policy import parse_requirements, validate_dependency_policy


ROOT = Path(__file__).resolve().parents[1]


def test_repository_dependencies_are_exactly_pinned():
    dependencies = validate_dependency_policy(ROOT / "requirements.txt")
    assert [(item.name, item.version) for item in dependencies] == [
        ("openai", "3.1.0"),
        ("python-dotenv", "1.2.3"),
    ]


def test_unpinned_dependency_is_rejected(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("openai\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exact == pins"):
        parse_requirements(path)


def test_duplicate_dependency_is_rejected(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("openai==3.1.0\nopenai==3.1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate dependency"):
        parse_requirements(path)


def test_non_requirement_directive_is_rejected(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("-r other.txt\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exact == pins"):
        parse_requirements(path)


def test_comments_and_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# runtime\n\nOpenAI==3.1.0\n", encoding="utf-8")
    assert parse_requirements(path) == (parse_requirements(ROOT / "requirements.txt")[0],)
