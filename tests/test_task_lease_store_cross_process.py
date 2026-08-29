import multiprocessing
import time

from runtime.task_lease_store import DurableTaskLeaseStore


def _worker_acquire(root, worker_id, lease_id, ttl_s, ready, result):
    store = DurableTaskLeaseStore(root)
    lease = store.acquire("TASK-001", worker_id, lease_id, ttl_s)
    result.put(("acquire", worker_id, lease is not None))
    if lease is not None:
        ready.set()
        time.sleep(0.15)


def _worker_late_commit(root, ready, result):
    store = DurableTaskLeaseStore(root)
    ready.wait(timeout=5)
    time.sleep(0.08)
    lease = store.acquire("TASK-001", "worker-b", "lease-b", 1.0)
    if lease is None:
        result.put(("takeover", False, None))
        return

    applied = []
    try:
        store.commit_if_owner(
            "TASK-001",
            "worker-a",
            "lease-a",
            lambda: applied.append("stale"),
        )
    except PermissionError as exc:
        result.put(("late_commit", False, str(exc), applied))
    else:
        result.put(("late_commit", True, None, applied))


def test_durable_lease_store_serializes_acquire_across_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    result = context.Queue()

    first = context.Process(
        target=_worker_acquire,
        args=(str(tmp_path), "worker-a", "lease-a", 1.0, ready, result),
    )
    second = context.Process(
        target=_worker_acquire,
        args=(str(tmp_path), "worker-b", "lease-b", 1.0, context.Event(), result),
    )

    first.start()
    assert ready.wait(timeout=5)
    second.start()

    outcomes = [result.get(timeout=5), result.get(timeout=5)]
    first.join(timeout=5)
    second.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert sorted(outcomes) == [
        ("acquire", "worker-a", True),
        ("acquire", "worker-b", False),
    ]


def test_late_commit_after_cross_process_takeover_is_rejected(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    result = context.Queue()

    first = context.Process(
        target=_worker_acquire,
        args=(str(tmp_path), "worker-a", "lease-a", 0.05, ready, result),
    )
    second = context.Process(
        target=_worker_late_commit,
        args=(str(tmp_path), ready, result),
    )

    first.start()
    second.start()

    outcomes = [result.get(timeout=5), result.get(timeout=5)]
    first.join(timeout=5)
    second.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert ("acquire", "worker-a", True) in outcomes
    assert ("late_commit", False, "Worker lease ownership mismatch", []) in outcomes
