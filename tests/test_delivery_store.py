import multiprocessing

from runtime.delivery_store import DurableDeliveryStore


def _begin(root, key, result):
    store = DurableDeliveryStore(root)
    decision = store.begin(key)
    result.put((decision.accepted, decision.duplicate, decision.status))


def test_delivery_identity_survives_new_store_instance(tmp_path):
    first = DurableDeliveryStore(tmp_path)
    assert first.begin("delivery-001").accepted is True
    assert first.complete("delivery-001").status == "committed"

    second = DurableDeliveryStore(tmp_path)
    decision = second.begin("delivery-001")

    assert decision.accepted is False
    assert decision.duplicate is True
    assert decision.status == "committed"


def test_duplicate_delivery_does_not_execute_callback(tmp_path):
    store = DurableDeliveryStore(tmp_path)
    applied = []

    assert store.commit("delivery-001", lambda: applied.append("once") or "result") == "result"
    assert store.commit("delivery-001", lambda: applied.append("twice") or "duplicate") is None

    assert applied == ["once"]
    assert store.status("delivery-001").status == "committed"


def test_processing_delivery_is_visible_after_restart(tmp_path):
    first = DurableDeliveryStore(tmp_path)
    assert first.begin("delivery-001").status == "processing"

    second = DurableDeliveryStore(tmp_path)
    decision = second.begin("delivery-001")

    assert decision.accepted is False
    assert decision.duplicate is True
    assert decision.status == "processing"


def test_independent_processes_can_reserve_delivery_only_once(tmp_path):
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    first = context.Process(target=_begin, args=(str(tmp_path), "delivery-001", result))
    second = context.Process(target=_begin, args=(str(tmp_path), "delivery-001", result))

    first.start()
    second.start()
    outcomes = [result.get(timeout=5), result.get(timeout=5)]
    first.join(timeout=5)
    second.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert sorted(outcomes) == [
        (False, True, "processing"),
        (True, False, "processing"),
    ]
