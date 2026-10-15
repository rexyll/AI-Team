from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from runtime.cancellation import CancellationRequested, CancellationToken


class TimeoutExceeded(RuntimeError):
    """Raised when a task exceeds its configured execution deadline."""


@dataclass(frozen=True)
class TimeoutSnapshot:
    """Read-only timeout state."""

    timeout_s: float | None
    started_at: float
    deadline: float | None
    expired: bool


class TimeoutController:
    """Monotonic cooperative timeout controller.

    A timeout is a control-plane event. It requests cancellation through the
    supplied token and never mutates task failure/retry state itself.
    """

    def __init__(
        self,
        timeout_s: float | None,
        *,
        token: CancellationToken | None = None,
        clock=monotonic,
    ) -> None:
        if timeout_s is not None:
            if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
                raise TypeError("timeout_s must be a positive number or None")
            if timeout_s <= 0:
                raise ValueError("timeout_s must be positive")
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken or None")
        self._timeout_s = float(timeout_s) if timeout_s is not None else None
        self._token = token or CancellationToken()
        self._clock = clock
        self._started_at = clock()
        self._deadline = (
            self._started_at + self._timeout_s
            if self._timeout_s is not None
            else None
        )
        self._expired = False

    @property
    def token(self) -> CancellationToken:
        return self._token

    @property
    def expired(self) -> bool:
        self.check()
        return self._expired

    def snapshot(self) -> TimeoutSnapshot:
        self.check()
        return TimeoutSnapshot(
            timeout_s=self._timeout_s,
            started_at=self._started_at,
            deadline=self._deadline,
            expired=self._expired,
        )

    def remaining(self) -> float | None:
        if self._deadline is None:
            return None
        remaining = self._deadline - self._clock()
        return max(0.0, remaining)

    def check(self) -> bool:
        if self._expired:
            return True
        if self._deadline is None:
            return False
        if self._clock() < self._deadline:
            return False
        self._expired = True
        self._token.request("task timeout exceeded")
        return True

    def raise_if_expired(self) -> None:
        if self.check():
            raise TimeoutExceeded("task timeout exceeded")
        try:
            self._token.raise_if_requested()
        except CancellationRequested:
            raise
