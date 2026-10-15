import threading
import time

from runtime.safe_tool_batch_executor import execute_safe_tool_batch


def _call(name: str, **arguments):
    return {"name": name, "arguments": arguments}


def test_safe_batch_executes_concurrently_and_preserves_input_order():
    started: list[str] = []
    lock = threading.Lock()

    def executor(name, arguments):
        path = arguments["path"]
        with lock:
            started.append(path)
        if path == "a.py":
            time.sleep(0.03)
        return f"{name}:{path}"

    calls = [_call("read_file", path="a.py"), _call("read_file", path="b.py")]
    decision, results = execute_safe_tool_batch(calls, executor, max_workers=2)

    assert decision.safe is True
    assert results == ["read_file:a.py", "read_file:b.py"]
    assert set(started) == {"a.py", "b.py"}


def test_unsafe_batch_is_not_executed():
    executed = []

    def executor(name, arguments):
        executed.append((name, arguments))
        return "unexpected"

    decision, results = execute_safe_tool_batch(
        [_call("read_file", path="a.py"), _call("write_file", path="b.py", content="x")],
        executor,
    )

    assert decision.safe is False
    assert results == []
    assert executed == []


def test_executor_exception_is_not_hidden():
    def executor(name, arguments):
        raise RuntimeError("boom")

    calls = [_call("read_file", path="a.py"), _call("read_file", path="b.py")]
    try:
        execute_safe_tool_batch(calls, executor, max_workers=2)
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("executor exception must propagate")
