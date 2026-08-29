from multiprocessing import get_context

import pytest

from runtime.task_result_store import DurableTaskResultStore


def test_commit_persists_result_and_same_delivery_is_duplicate(tmp_path):
    store = DurableTaskResultStore(tmp_path)

    first = store.commit("TASK-001", "delivery-a", {"value": 42})
    second = store.commit("TASK-001", "delivery-a", {"value": 999})

    assert first.accepted is True
    assert first.duplicate is False
    assert second.accepted is False
    assert second.duplicate is True
    assert store.get("TASK-001").result == {"value": 42}


def test_result_survives_store_restart(tmp_path):
    DurableTaskResultStore(tmp_path).commit("TASK-001", "delivery-a", {"ok": True})

    restored = DurableTaskResultStore(tmp_path).get("TASK-001")
    assert restored is not None
    assert restored.delivery_key == "delivery-a"
    assert restored.result == {"ok": True}


def test_different_delivery_cannot_overwrite_existing_result(tmp_path):
    store = DurableTaskResultStore(tmp_path)
    store.commit("TASK-001", "delivery-a", {"value": 1})

    with pytest.raises(ValueError, match="already has a committed result"):
        store.commit("TASK-001", "delivery-b", {"value": 2})


def test_independent_processes_have_one_result_commit(tmp_path):
    def _commit(root, result):
        store = DurableTaskResultStore(root)
        try:
            decision = store.commit("TASK-001", "delivery-a", {"value": 1})
            result.put((decision.accepted, decision.duplicate))
        except Exception as exc:
            result.put(("error", str(exc)))

    context = get_context("spawn")
    result = context.Queue()
    first = context.Process(target=_commit, args=(str(tmp_path), result))
    second = context.Process(target=_commit, args=(str(tmp_path), result))
    first.start()
    second.start()

    outcomes = [result.get(timeout=5), result.get(timeout=5)]
    first.join(timeout=5)
    second.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert sorted(outcomes) == [(False, True), (True, False)]
