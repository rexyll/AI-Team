from runtime.tool_loop_cache import ToolResultCache


def test_repeated_cached_reads_have_bounded_context_cost() -> None:
    """Regression guard for the duplicate-read context amplification case.

    The old behavior injected the complete cached result for every duplicate.
    This contract models the benchmark shape (one original read + nine exact
    duplicates) and ensures the duplicate evidence stays dramatically smaller
    than replaying the full result nine times.
    """
    source = "from package import dependency\n" + ("body\n" * 2000) + "# important footer"
    duplicate_count = 9
    cache = ToolResultCache()
    cache.store(
        tool_name="read_file",
        arguments={"path": "src/example.py"},
        result=source,
        execution_id="call-1",
    )

    hit_messages = []
    for _ in range(duplicate_count):
        hit = cache.lookup("read_file", {"path": "src/example.py"})
        assert hit is not None
        hit_messages.append(hit.context_evidence())

    compacted_chars = sum(len(message) for message in hit_messages)
    replayed_chars = len(source) * duplicate_count

    assert compacted_chars < replayed_chars * 0.10
    assert all("TOOL RESULT REUSED" in message for message in hit_messages)
    assert all(source not in message for message in hit_messages)
    assert cache.hits == duplicate_count
    assert cache.misses == 0
