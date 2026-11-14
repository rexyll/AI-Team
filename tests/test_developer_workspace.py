from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
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






def _crash_during_multi_file_merge(root: str, connection) -> None:
    import runtime.developer_workspace as workspace_module

    manager = DeveloperWorkspaceManager(root)
    lease = manager.issue("TASK-MERGE-CRASH")
    (lease.root / "a.txt").write_text("changed-a", encoding="utf-8")
    (lease.root / "b.txt").write_text("changed-b", encoding="utf-8")
    original_replace = workspace_module.os.replace
    canonical_a = Path(root) / "a.txt"

    def replace_then_crash(source, destination):
        original_replace(source, destination)
        if Path(destination) == canonical_a:
            connection.send("first-file-applied")
            connection.close()
            os._exit(17)

    workspace_module.os.replace = replace_then_crash
    manager.merge(lease)


def _crash_lease_owner(root: str, result_connection) -> None:
    manager = DeveloperWorkspaceManager(root)
    lease = manager.issue("TASK-CRASHED")
    result_connection.send(str(lease.root))
    result_connection.close()
    # Simulate abrupt process death: do not execute manager.discard().
    os._exit(0)


def _cross_process_merge_worker(root: str, task_id: str, value: str, ready, start, results) -> None:
    manager = DeveloperWorkspaceManager(root)
    lease = manager.issue(task_id)
    (lease.root / "shared.txt").write_text(value, encoding="utf-8")
    ready.set()
    if not start.wait(10):
        results.put("timeout")
        manager.discard(lease)
        return
    try:
        manager.merge(lease)
        results.put("merged")
    except WorkspaceMergeConflict:
        results.put("conflict")
    finally:
        manager.discard(lease)


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



def test_orchestrator_discards_workspace_when_developer_raises(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    task = Task(
        id="TASK-008",
        title="write then raise",
        description="write then raise",
        role="developer",
        status="ready",
        context={"workspace_root": str(root)},
    )
    manager = TaskManager([task])

    class _Workflow:
        def execute(self, task_id: str, *, execution_id: str | None = None):
            write_file("partial.py", "PARTIAL = True\\n")
            raise RuntimeError("simulated developer timeout")

    monkeypatch.setattr(
        orchestrator_module,
        "create_task_workflow",
        lambda **kwargs: _Workflow(),
    )
    orchestrator = Orchestrator(manager, _DeveloperRouter())

    orchestrator._execute_task(task, execution_id="EXEC-008")

    assert not (root / "partial.py").exists()
    assert task.status in {"failed", "ready"}
    lease_parent = root.parent / ".ai-team-dev-workspaces"
    assert not list(lease_parent.glob("TASK-008-*"))


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



def test_workspace_managers_serialize_cross_process_merges(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    (root / "shared.txt").write_text("base", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    ready_a, ready_b = context.Event(), context.Event()
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_cross_process_merge_worker,
            args=(str(root), "TASK-PROC-A", "A", ready_a, start, results),
        ),
        context.Process(
            target=_cross_process_merge_worker,
            args=(str(root), "TASK-PROC-B", "B", ready_b, start, results),
        ),
    ]
    for worker in workers:
        worker.start()
    try:
        assert ready_a.wait(15)
        assert ready_b.wait(15)
        start.set()
        outcomes = sorted([results.get(timeout=15), results.get(timeout=15)])
    finally:
        start.set()
        for worker in workers:
            worker.join(timeout=15)
            if worker.is_alive():
                worker.terminate()
                worker.join()
    assert outcomes == ["conflict", "merged"]
    assert (root / "shared.txt").read_text(encoding="utf-8") in {"A", "B"}





def test_workspace_manager_fails_closed_on_corrupt_merge_journal(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    manager = DeveloperWorkspaceManager(root)
    transaction_root = manager._lease_parent / ".txn-corrupt"
    transaction_root.mkdir()
    (transaction_root / "journal.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(RuntimeError, match="cannot safely recover developer workspace transaction"):
        DeveloperWorkspaceManager(root)

    assert transaction_root.exists()


def test_workspace_manager_rolls_back_partial_multi_file_merge_after_process_crash(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    (root / "a.txt").write_text("base-a", encoding="utf-8")
    (root / "b.txt").write_text("base-b", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    worker = context.Process(
        target=_crash_during_multi_file_merge,
        args=(str(root), child_connection),
    )
    worker.start()
    child_connection.close()
    try:
        assert parent_connection.recv() == "first-file-applied"
        worker.join(timeout=15)
        assert not worker.is_alive()
        assert worker.exitcode == 17

        manager = DeveloperWorkspaceManager(root)

        assert (root / "a.txt").read_text(encoding="utf-8") == "base-a"
        assert (root / "b.txt").read_text(encoding="utf-8") == "base-b"
        assert not list(manager._lease_parent.glob(".txn-*"))
    finally:
        parent_connection.close()
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=15)


def test_workspace_manager_recovers_lease_after_owner_process_is_terminated(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    worker = context.Process(
        target=_crash_lease_owner,
        args=(str(root), child_connection),
    )
    worker.start()
    child_connection.close()
    try:
        lease_root = Path(parent_connection.recv())
        worker.join(timeout=15)
        assert not worker.is_alive()
        assert worker.exitcode == 0
        assert lease_root.is_dir()

        manager = DeveloperWorkspaceManager(root)

        assert not lease_root.exists()
        assert not manager._metadata_path(lease_root).exists()
    finally:
        parent_connection.close()
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=15)


def test_workspace_manager_recovers_dead_process_leases(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    manager = DeveloperWorkspaceManager(root)
    lease = manager.issue("TASK-STALE")
    metadata_path = manager._metadata_path(lease.root)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["owner_pid"] = 2**30
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    recovered = DeveloperWorkspaceManager(root)

    assert lease.root.name in recovered.recover_stale_leases() or not lease.root.exists()
    assert not lease.root.exists()
    assert not metadata_path.exists()


def test_workspace_manager_preserves_live_process_leases(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    manager = DeveloperWorkspaceManager(root)
    lease = manager.issue("TASK-LIVE")

    DeveloperWorkspaceManager(root)

    assert lease.root.is_dir()
    manager.discard(lease)


def test_workspace_manager_rejects_symlink_in_canonical_workspace(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "important.txt").write_text("protected", encoding="utf-8")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    manager = DeveloperWorkspaceManager(root)

    with pytest.raises(ValueError, match="symbolic links in the canonical workspace"):
        manager.issue("TASK-SYMLINK")


def test_workspace_lease_excludes_mutable_dependency_directories(tmp_path: Path) -> None:
    root = tmp_path / "deliverable"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("shared interpreter", encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("shared package", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("VALUE = 1", encoding="utf-8")
    manager = DeveloperWorkspaceManager(root)

    lease = manager.issue("TASK-DEPS")

    assert (lease.root / "src" / "main.py").is_file()
    assert not (lease.root / ".venv").exists()
    assert not (lease.root / "node_modules").exists()
    (lease.root / ".venv").mkdir()
    (lease.root / ".venv" / "injected.txt").write_text("not merged", encoding="utf-8")
    manager.merge(lease)
    assert not (root / ".venv" / "injected.txt").exists()
    manager.discard(lease)


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
