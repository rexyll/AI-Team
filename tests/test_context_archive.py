from runtime.context_archive import ContextArchive, build_task_archive_record
from security.workspace import (
    WorkspaceSandbox,
    get_active_sandbox,
    reset_active_sandbox,
    resolve_workspace_path,
    set_active_sandbox,
)


def record():
    return {
        "task_id": "TASK-001",
        "role": "developer",
        "title": "实现模块",
        "status": "completed",
        "message": "完成了实现",
        "developer_slot": 1,
        "merge_report": {"changed": ["a.py"], "added": ["b.py"], "deleted": []},
    }


def test_record_task_writes_file_and_refreshes_index(tmp_path):
    archive = ContextArchive(tmp_path, "proj-1")
    path = archive.record_task(record())
    assert path.is_file()
    entries = archive.index_summary()
    assert len(entries) == 1
    assert entries[0]["task_id"] == "TASK-001"
    assert entries[0]["changed_files"] == 2


def test_namespaces_are_isolated(tmp_path):
    ContextArchive(tmp_path, "proj-1").record_task(record())
    other = ContextArchive(tmp_path, "proj-2")
    assert other.index_summary() == []
    other.record_task(record())
    assert len(other.index_summary()) == 1
    assert len(ContextArchive(tmp_path, "proj-1").index_summary()) == 1


def test_unsafe_namespace_is_rejected(tmp_path):
    for bad in ("../escape", "a/b", "", ".."):
        try:
            ContextArchive(tmp_path, bad)
        except ValueError:
            continue
        raise AssertionError(f"namespace {bad!r} must be rejected")


def test_context_injection_lists_entries_or_is_empty(tmp_path):
    archive = ContextArchive(tmp_path, "proj-1")
    assert archive.context_injection() == ""
    archive.record_task(record())
    text = archive.context_injection()
    assert ".context-archive/" in text
    assert "tasks/TASK-001.json" in text
    assert "路径前缀" in text


def test_build_task_archive_record_extracts_feedback_and_history():
    task_dict = {
        "id": "TASK-009",
        "role": "developer",
        "title": "t",
        "status": "failed",
        "error": "boom",
        "result": {"message": "报告"},
        "context": {
            "tester_feedback": {"status": "failed"},
            "qa_feedback": {"verdict": "concerns"},
            "reviewer_feedback": {"decision": "retry"},
            "tool_execution_history": [{"execution_id": "e1"}],
        },
    }
    built = build_task_archive_record(task_dict, developer_slot=2, merge_report=None)
    assert built["task_id"] == "TASK-009"
    assert built["developer_slot"] == 2
    assert built["tester_feedback"] == {"status": "failed"}
    assert built["reviewer_feedback"] == {"decision": "retry"}
    assert built["tool_execution_history"] == [{"execution_id": "e1"}]


def test_active_sandbox_redirects_resolution_per_context():
    default_root = resolve_workspace_path(".")
    lease_root = default_root / ".dev-workspaces" / "lease-test"
    lease_root.mkdir(parents=True, exist_ok=True)
    (lease_root / "lease-file.txt").write_text("lease", encoding="utf-8")
    token = set_active_sandbox(WorkspaceSandbox(lease_root))
    try:
        resolved = resolve_workspace_path("lease-file.txt")
        assert resolved.name == "lease-file.txt"
        assert "lease-test" in str(resolved)
        assert get_active_sandbox() is not None
    finally:
        reset_active_sandbox(token)
    assert resolve_workspace_path(".") == default_root
    assert get_active_sandbox() is None


def test_safe_batch_workers_inherit_caller_sandbox():
    from runtime.safe_tool_batch_executor import execute_safe_tool_batch

    main_root = resolve_workspace_path(".")
    lease_root = main_root / ".dev-workspaces" / "batch-lease"
    (lease_root / "inner").mkdir(parents=True, exist_ok=True)
    (lease_root / "inner" / "seen.txt").write_text("x", encoding="utf-8")

    def probe(name, arguments):
        return str(resolve_workspace_path(arguments["path"]))

    token = set_active_sandbox(WorkspaceSandbox(lease_root))
    try:
        _decision, results = execute_safe_tool_batch(
            [
                {"name": "list_files", "arguments": {"path": "."}},
                {"name": "list_files", "arguments": {"path": "inner"}},
            ],
            probe,
        )
    finally:
        reset_active_sandbox(token)
    assert len(results) == 2
    assert all("batch-lease" in item for item in results)
    assert resolve_workspace_path(".") == main_root


def test_retarget_preserves_mandated_directory_folding(tmp_path):
    main_root = tmp_path / "base"
    anchored = main_root / "workspace"
    anchored.mkdir(parents=True)
    sandbox = WorkspaceSandbox(anchored, folded_prefix="workspace")
    lease = sandbox.retarget(anchored / ".dev-workspaces" / "T1")
    assert lease.folded_prefix == sandbox.folded_prefix
    # The folding strips the literal mandated prefix inside the lease too.
    direct = lease.resolve("workspace/expense-reporter/pkg.py")
    assert direct == lease.root / "expense-reporter" / "pkg.py"
