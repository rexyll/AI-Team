from pathlib import Path

from benchmarks.real_developer.fixture import isolated_benchmark_workspace
from security.workspace import PROJECT_ROOT, get_default_workspace_root


def test_isolated_benchmark_workspace_is_nested_under_authorized_project_root() -> None:
    before = get_default_workspace_root()
    with isolated_benchmark_workspace() as root:
        resolved = Path(root).resolve()
        assert resolved != PROJECT_ROOT.resolve()
        resolved.relative_to(PROJECT_ROOT.resolve())
        assert get_default_workspace_root() == resolved
    assert get_default_workspace_root() == before
