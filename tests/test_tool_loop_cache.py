from runtime.tool_loop_cache import CACHEABLE_TOOLS, MUTATING_TOOLS, ToolResultCache


def test_exact_read_only_call_is_reused_without_rerunning() -> None:
    cache = ToolResultCache()
    first = {"path": "runtime/task.py"}
    result = {"content": "task source", "size": 11}

    cache.store(tool_name="read_file", arguments=first, result=result, execution_id="CALL-1")
    hit = cache.lookup(tool_name="read_file", arguments={"path": "runtime/task.py"})

    assert hit is not None
    assert hit.result == result
    assert hit.source_execution_id == "CALL-1"
    assert cache.hits == 1
    assert cache.misses == 0


def test_cached_result_exposes_compact_context_evidence() -> None:
    cache = ToolResultCache()
    cache.store(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="very large source content",
        execution_id="CALL-1",
    )

    hit = cache.lookup("read_file", {"path": "runtime/task.py"})

    assert hit is not None
    marker = hit.context_evidence()
    assert "TOOL RESULT REUSED" in marker
    assert "CALL-1" in marker
    assert "very large source content" not in marker


def test_cache_presence_probe_does_not_mutate_lookup_counters_or_recency() -> None:
    cache = ToolResultCache(max_entries=2)
    cache.store(tool_name="read_file", arguments={"path": "a.py"}, result="a", execution_id="CALL-1")
    cache.store(tool_name="read_file", arguments={"path": "b.py"}, result="b", execution_id="CALL-2")

    assert cache.contains("read_file", {"path": "a.py"}) is True
    assert cache.contains("read_file", {"path": "missing.py"}) is False
    assert cache.hits == 0
    assert cache.misses == 0

    cache.store(tool_name="read_file", arguments={"path": "c.py"}, result="c", execution_id="CALL-3")
    assert cache.lookup("read_file", {"path": "a.py"}) is None
    assert cache.lookup("read_file", {"path": "b.py"}) is not None
    assert cache.lookup("read_file", {"path": "c.py"}) is not None


def test_canonical_arguments_are_order_independent() -> None:
    cache = ToolResultCache()
    cache.store(
        tool_name="list_files",
        arguments={"path": ".", "recursive": True},
        result=["a.py"],
        execution_id="CALL-1",
    )

    hit = cache.lookup(
        "list_files",
        arguments={"recursive": True, "path": "."},
    )

    assert hit is not None
    assert hit.result == ["a.py"]


def test_mutating_tool_invalidates_previous_read_result() -> None:
    cache = ToolResultCache()
    cache.store(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="old",
        execution_id="CALL-1",
    )

    cache.invalidate_for("write_file")

    assert cache.lookup("read_file", {"path": "runtime/task.py"}) is None
    assert cache.invalidations == 1


def test_mutating_and_unknown_tools_are_never_cacheable() -> None:
    cache = ToolResultCache()

    for tool_name in (*sorted(MUTATING_TOOLS), "unknown_tool"):
        cache.store(
            tool_name=tool_name,
            arguments={"path": "runtime/task.py"},
            result="must not cache",
            execution_id="CALL-1",
        )
        assert cache.lookup(tool_name, {"path": "runtime/task.py"}) is None

    assert CACHEABLE_TOOLS == frozenset({"read_file", "list_files"})


def test_cached_result_is_defensively_copied() -> None:
    cache = ToolResultCache()
    original = {"items": ["a.py"]}
    cache.store(
        tool_name="list_files",
        arguments={"path": "."},
        result=original,
        execution_id="CALL-1",
    )

    hit = cache.lookup("list_files", {"path": "."})
    assert hit is not None
    hit.result["items"].append("mutated-by-caller")

    second = cache.lookup("list_files", {"path": "."})
    assert second is not None
    assert second.result == {"items": ["a.py"]}


def test_cache_evicts_oldest_entry_when_window_is_full() -> None:
    cache = ToolResultCache(max_entries=2)
    cache.store(tool_name="read_file", arguments={"path": "a.py"}, result="a", execution_id="CALL-1")
    cache.store(tool_name="read_file", arguments={"path": "b.py"}, result="b", execution_id="CALL-2")
    cache.store(tool_name="read_file", arguments={"path": "c.py"}, result="c", execution_id="CALL-3")

    assert cache.lookup("read_file", {"path": "a.py"}) is None
    assert cache.lookup("read_file", {"path": "b.py"}) is not None
    assert cache.lookup("read_file", {"path": "c.py"}) is not None


def test_cache_hit_refreshes_window_recency() -> None:
    cache = ToolResultCache(max_entries=2)
    cache.store(tool_name="read_file", arguments={"path": "a.py"}, result="a", execution_id="CALL-1")
    cache.store(tool_name="read_file", arguments={"path": "b.py"}, result="b", execution_id="CALL-2")
    assert cache.lookup("read_file", {"path": "a.py"}) is not None
    cache.store(tool_name="read_file", arguments={"path": "c.py"}, result="c", execution_id="CALL-3")

    assert cache.lookup("read_file", {"path": "a.py"}) is not None
    assert cache.lookup("read_file", {"path": "b.py"}) is None
