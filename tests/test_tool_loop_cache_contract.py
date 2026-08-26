from runtime.tool_loop_cache import ToolResultCache


def test_exact_read_result_is_reused():
    cache = ToolResultCache()
    cache.store(tool_name="read_file", arguments={"path": "a.py"}, result="content", execution_id="EXEC-1")

    hit = cache.lookup("read_file", {"path": "a.py"})

    assert hit is not None
    assert hit.result == "content"
    assert hit.source_execution_id == "EXEC-1"
    assert cache.hits == 1


def test_mutating_tool_invalidates_cached_reads():
    cache = ToolResultCache()
    cache.store(tool_name="read_file", arguments={"path": "a.py"}, result="old", execution_id="EXEC-1")

    cache.invalidate_for("write_file")

    assert cache.lookup("read_file", {"path": "a.py"}) is None
    assert cache.invalidations == 1


def test_non_cacheable_tools_are_never_reused():
    cache = ToolResultCache()
    cache.store(tool_name="run_command", arguments={"command": "pytest -q"}, result="ok", execution_id="EXEC-1")

    assert cache.lookup("run_command", {"command": "pytest -q"}) is None
    assert cache.hits == 0


def test_cached_result_is_detached_from_stored_value():
    cache = ToolResultCache()
    original = {"items": ["a"]}
    cache.store(tool_name="list_files", arguments={"path": "."}, result=original, execution_id="EXEC-1")

    hit = cache.lookup("list_files", {"path": "."})
    hit.result["items"].append("mutated")

    second = cache.lookup("list_files", {"path": "."})
    assert second.result == {"items": ["a"]}
