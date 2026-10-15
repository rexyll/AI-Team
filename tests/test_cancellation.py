import threading

import pytest

from runtime.cancellation import (
    CancellationRequested,
    CancellationToken,
)


def test_token_starts_active_and_snapshot_is_read_only():
    token = CancellationToken()

    assert token.requested is False
    assert token.snapshot().requested is False
    assert token.snapshot().reason is None


def test_request_is_monotonic_and_preserves_first_reason():
    token = CancellationToken()

    first = token.request("operator stopped workflow")
    second = token.request("later reason")

    assert first.requested is True
    assert first.reason == "operator stopped workflow"
    assert second == first
    assert token.requested is True


def test_request_without_reason_is_idempotent():
    token = CancellationToken()

    assert token.request().reason is None
    assert token.request("too late").reason is None


def test_raise_if_requested_is_noop_before_request():
    CancellationToken().raise_if_requested()


def test_raise_if_requested_raises_after_request():
    token = CancellationToken()
    token.request("cancel task")

    with pytest.raises(CancellationRequested, match="cancel task"):
        token.raise_if_requested()


def test_invalid_reason_is_rejected_without_requesting():
    token = CancellationToken()

    with pytest.raises(ValueError, match="cancellation reason"):
        token.request("   ")

    assert token.requested is False


def test_wait_observes_cancellation():
    token = CancellationToken()

    thread = threading.Thread(target=lambda: token.request("worker stopped"))
    thread.start()
    thread.join()

    assert token.wait(0) is True
    assert token.snapshot().reason == "worker stopped"


def test_concurrent_requests_remain_monotonic():
    token = CancellationToken()
    barrier = threading.Barrier(8)

    def request(index: int) -> None:
        barrier.wait()
        token.request(f"reason-{index}")

    threads = [threading.Thread(target=request, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snapshot = token.snapshot()
    assert snapshot.requested is True
    assert snapshot.reason in {f"reason-{index}" for index in range(8)}
    assert token.requested is True
