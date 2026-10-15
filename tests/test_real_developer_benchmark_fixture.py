from __future__ import annotations

from pathlib import Path

from benchmarks.real_developer.fixture import fixture_files, isolated_benchmark_workspace
from security.workspace import get_default_workspace_root


def test_fixture_manifest_contains_only_known_project_files() -> None:
    files = fixture_files()
    assert "app/utils/helpers.py" in files
    assert "tests/test_helpers.py" in files
    assert "docs/benchmark_reference.md" in files
    assert "tasks.json" not in files
    assert all(
        Path(path).is_relative_to(Path("app"))
        or Path(path).is_relative_to(Path("tests"))
        or Path(path).is_relative_to(Path("docs"))
        for path in files
    )
    assert len(files["docs/benchmark_reference.md"]) >= 10_000


def test_isolated_workspace_materializes_fixture_and_restores_root() -> None:
    before = get_default_workspace_root()

    with isolated_benchmark_workspace() as root:
        assert get_default_workspace_root() == root
        assert (root / "app/utils/helpers.py").is_file()
        assert (root / "tests/test_helpers.py").is_file()
        assert (root / "docs/benchmark_reference.md").stat().st_size >= 10_000
        assert not (root / "tasks.json").exists()

    assert get_default_workspace_root() == before
