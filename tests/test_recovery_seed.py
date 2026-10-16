from runtime.recovery_seed import build_recovery_seed, collect_history_paths


def history_payload():
    return [
        {"execution_id": "e1", "tool_name": "list_files", "arguments": {"path": "."}},
        {"execution_id": "e2", "tool_name": "read_file", "arguments": {"path": "pkg/core.py"}},
        {"execution_id": "e3", "tool_name": "write_file", "arguments": {"path": "pkg/core.py"}},
        {"execution_id": "e4", "tool_name": "read_file", "arguments": {"path": "pkg/other.py"}},
        {"execution_id": "e5", "tool_name": "run_command", "arguments": {"command": "python -m pytest"}},
    ]


def test_collect_history_paths_dedupes_and_filters():
    paths = collect_history_paths(history_payload())
    assert paths == ["pkg/core.py", "pkg/other.py"]


def test_collect_history_paths_handles_invalid_payloads():
    assert collect_history_paths(None) == []
    assert collect_history_paths(["junk", 42]) == []


def test_seed_inlines_file_contents_and_states_the_rules():
    seed = build_recovery_seed(
        "repeated identical list_files calls",
        [("pkg/core.py", "def core():\n    return 1\n")],
    )
    assert "恢复检查点" in seed
    assert "repeated identical list_files calls" in seed
    assert "----- pkg/core.py -----" in seed
    assert "def core():" in seed
    assert "禁止再用 read_file" in seed
    assert "python -m pytest" in seed


def test_seed_caps_per_file_and_total_budget():
    entries = [(f"file_{i}.py", "x" * 6000) for i in range(10)]
    seed = build_recovery_seed("reason", entries)
    assert "已达恢复检查点内容上限" in seed
    assert len(seed) < 22000


def test_seed_lists_unreadable_paths_without_inventing_content():
    seed = build_recovery_seed("reason", [("gone.py", None)])
    assert "gone.py" in seed
    assert "内容不可读" in seed
    assert "----- gone.py -----\n\n" not in seed
