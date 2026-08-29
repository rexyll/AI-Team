import multiprocessing

from runtime.delivery_audit import DurableDeliveryAuditStore


def _record(root, key, action):
    DurableDeliveryAuditStore(root).record(key, action)


def test_audit_records_are_durable_and_filterable(tmp_path):
    store = DurableDeliveryAuditStore(tmp_path)
    store.record("delivery-001", "begin", status_after="processing")
    store.record("delivery-001", "complete", status_before="processing", status_after="committed")
    store.record("delivery-002", "begin", status_after="processing")

    records = store.records("delivery-001")
    assert [record.action for record in records] == ["begin", "complete"]
    assert records[1].status_before == "processing"
    assert records[1].status_after == "committed"
    assert store.records()[2].delivery_key == "delivery-002"


def test_audit_survives_reopening_store(tmp_path):
    DurableDeliveryAuditStore(tmp_path).record(
        "delivery-001", "reconciliation_required", metadata={"state": "unknown"}
    )

    reopened = DurableDeliveryAuditStore(tmp_path)
    record = reopened.records("delivery-001")[0]
    assert record.action == "reconciliation_required"
    assert record.metadata == {"state": "unknown"}


def test_independent_processes_append_audit_without_losing_records(tmp_path):
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_record, args=(str(tmp_path), f"delivery-{index}", "begin"))
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    records = DurableDeliveryAuditStore(tmp_path).records()
    assert len(records) == 4
    assert {record.delivery_key for record in records} == {
        "delivery-0",
        "delivery-1",
        "delivery-2",
        "delivery-3",
    }
