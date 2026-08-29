import pytest

from runtime.cancellation import CancellationRequested, CancellationToken
from runtime.timeout import TimeoutController, TimeoutExceeded


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_timeout_is_disabled_when_timeout_is_none():
    clock = FakeClock()
    controller = TimeoutController(None, clock=clock)

    assert controller.expired is False
    assert controller.remaining() is None
    assert controller.snapshot().deadline is None


def test_timeout_expires_at_deadline_and_requests_cancellation():
    clock = FakeClock()
    token = CancellationToken()
    controller = TimeoutController(5, token=token, clock=clock)

    clock.value = 104.999
    assert controller.check() is False
    assert token.requested is False

    clock.value = 105.0
    assert controller.check() is True
    assert controller.expired is True
    assert token.requested is True
    assert token.snapshot().reason == "task timeout exceeded"


def test_timeout_remaining_never_goes_negative():
    clock = FakeClock()
    controller = TimeoutController(5, clock=clock)

    clock.value = 108.0
    assert controller.remaining() == 0.0


def test_timeout_raise_is_distinct_from_normal_cancellation():
    clock = FakeClock()
    controller = TimeoutController(5, clock=clock)
    clock.value = 105.0

    with pytest.raises(TimeoutExceeded, match="task timeout exceeded"):
        controller.raise_if_expired()


def test_preexisting_cancellation_is_preserved():
    clock = FakeClock()
    token = CancellationToken()
    token.request("operator stopped task")
    controller = TimeoutController(5, token=token, clock=clock)

    with pytest.raises(CancellationRequested, match="operator stopped task"):
        controller.raise_if_expired()

    assert controller.expired is False
    assert token.snapshot().reason == "operator stopped task"


def test_timeout_is_idempotent_after_expiry():
    clock = FakeClock()
    controller = TimeoutController(1, clock=clock)
    clock.value = 101.0

    first = controller.snapshot()
    second = controller.snapshot()

    assert first == second
    assert controller.token.snapshot().reason == "task timeout exceeded"
