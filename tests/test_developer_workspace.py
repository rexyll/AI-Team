from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import core.orchestrator as orchestrator_module
from core.orchestrator import Orchestrator
from runtime.task import Task
from runtime.task_manager import TaskManager
from tools.filesystem import write_file

from runtime.developer_workspace import (
    DeveloperWorkspaceManager,
    WorkspaceMergeConflict,
)
from security.workspace import resolve_workspace_path, workspace_scope



class _DeveloperRouter:
    def get_developer_for_task(self, task_id: str):
        return object()

    def get_agent(self, role: str):
        return object()


def test_orchestrator_merges_successful_developer_workspace(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    task = Task(
        id="TASK-006",
        title="write an artifact",
        description="write an artifact",
        role="developer",
        status="ready",
        context={"workspace_root": str(root)},
    )
    manager = TaskManager([task])

    class _Workflow:
        def execute(self, task_id: str, *, execution_id: str | None = None):
            write_file("generated.py", "VALUE = 42\n")
            manager.get_task(task_id).status = "completed"

    monkeypatch.setattr(
        orchestrator_module,
        "create_task_workflow",
        lambda **kwargs: _Workflow(),
    )
    orchestrator = Orchestrator(manager, _DeveloperRouter())

    orchestrator._execute_task(task, execution_id="EXEC-006")

    assert (root / "generated.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    assert task.context["workspace_merge"]["added"] == ["generated.py"]


def test_orchestrator_discards_failed_developer_workspace(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    task = Task(
        id="TASK-007",
        title="write then fail",
        description="write then fail",
        role="developer",
        status="ready",
        context={"workspace_root": str(root)},
    )
    manager = TaskManager([task])

    class _Workflow:
        def execute(self, task_id: str, *, execution_id: str | None = None):
            write_file("partial.py", "PARTIAL = True\n")
            manager.get_task(task_id).status = "failed"

    monkeypatch.setattr(
        orchestrator_module,
        "create_task_workflow",
        lambda **kwargs: _Workflow(),
    )
    orchestrator = Orchestrator(manager, _DeveloperRouter())

    orchestrator._execute_task(task, execution_id="EXEC-007")

    assert not (root / "partial.py").exists()
    assert task.context["workspace_discarded"] is True


def test_workspace_lease_merges_changed_added_and_deleted_files(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    (root / "change.txt").write_text("before", encoding="utf-8")
    (root / "delete.txt").write_text("remove", encoding="utf-8")
    manager = DeveloperWorkspaceManager(root)

    lease = manager.issue("TASK-001")
    (lease.root / "change.txt").write_text("after", encoding="utf-8")
    (lease.root / "new.txt").write_text("new", encoding="utf-8")
    (lease.root / "delete.txt").unlink()

    report = manager.merge(lease)

    assert (root / "change.txt").read_text(encoding="utf-8") == "after"
    assert (root / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (root / "delete.txt").exists()
    assert report.changed == ("change.txt",)
    assert report.added == ("new.txt",)
    assert report.deleted == ("delete.txt",)
    manager.discard(lease)


def test_workspace_lease_rejects_same_path_concurrent_modification(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    target = root / "shared.txt"
    target.write_text("base", encoding="utf-8")
    manager = DeveloperWorkspaceManager(root)

    lease = manager.issue("TASK-002")
    (lease.root / "shared.txt").write_text("developer", encoding="utf-8")
    target.write_text("external", encoding="utf-8")

    with pytest.raises(WorkspaceMergeConflict, match="shared.txt"):
        manager.merge(lease)

    assert target.read_text(encoding="utf-8") == "external"
    manager.discard(lease)


def test_workspace_leases_merge_disjoint_parallel_changes(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    manager = DeveloperWorkspaceManager(root)
    first = manager.issue("TASK-003")
    second = manager.issue("TASK-004")
    (first.root / "first.py").write_text("FIRST = 1\n", encoding="utf-8")
    (second.root / "second.py").write_text("SECOND = 2\n", encoding="utf-8")

    manager.merge(first)
    manager.merge(second)

    assert (root / "first.py").is_file()
    assert (root / "second.py").is_file()
    manager.discard(first)
    manager.discard(second)


def test_workspace_lease_rejects_path_traversal_task_ids(tmp_path: Path) -> None:
    manager = DeveloperWorkspaceManager(tmp_path / "deliverable")

    with pytest.raises(ValueError, match="safe non-empty identifier"):
        manager.issue("../outside")


def test_workspace_lease_rejects_symlinks_created_by_developer(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    manager = DeveloperWorkspaceManager(root)
    lease = manager.issue("TASK-005")
    try:
        (lease.root / "escape.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(ValueError, match="symbolic links"):
        manager.merge(lease)
    manager.discard(lease)



def test_workspace_scope_preserves_folded_deliverable_prefix(tmp_path: Path) -> None:
    root = tmp_path / "isolated-deliverable"
    root.mkdir()

    with workspace_scope(root, folded_prefix="workspace/e2e_artifact"):
        resolved = resolve_workspace_path("workspace/e2e_artifact/src/main.py")

    assert resolved == (root / "src" / "main.py").resolve()

def test_workspace_scope_is_context_local_across_threads(tmp_path: Path) -> None:
    roots = [tmp_path / "task-a", tmp_path / "task-b"]
    for root in roots:
        root.mkdir()

    def resolve(root: Path) -> Path:
        with workspace_scope(root):
            return resolve_workspace_path(".")

    with ThreadPoolExecutor(max_workers=2) as pool:
        resolved = list(pool.map(resolve, roots))

    assert resolved == [root.resolve() for root in roots]
