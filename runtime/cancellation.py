from __future__ import annotations

from dataclasses import dataclass
from threading import Event, RLock


class CancellationRequested(RuntimeError):
    """Raised when cooperative cancellation has been requested."""


@dataclass(frozen=True)
class CancellationSnapshot:
    """Read-only cancellation state exposed to callers."""

    requested: bool
    reason: str | None


class CancellationToken:
    """Thread-safe cooperative cancellation token.

    Cancellation is explicit and monotonic: once requested, a token can never
    return to the active state. Requesting cancellation repeatedly is idempotent
    and preserves the first non-empty reason.
    """

    def __init__(self) -> None:
        self._event = Event()
        self._lock = RLock()
        self._reason: str | None = None

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self, reason: str | None = None) -> CancellationSnapshot:
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("cancellation reason must be a non-empty string or None")

        with self._lock:
            if not self._event.is_set():
                self._reason = reason.strip() if reason is not None else None
                self._event.set()
            return self.snapshot()

    def snapshot(self) -> CancellationSnapshot:
        with self._lock:
            return CancellationSnapshot(
                requested=self._event.is_set(),
                reason=self._reason,
            )

    def raise_if_requested(self) -> None:
        snapshot = self.snapshot()
        if snapshot.requested:
            suffix = f": {snapshot.reason}" if snapshot.reason else ""
            raise CancellationRequested(f"cancellation requested{suffix}")

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for cancellation; return whether cancellation was requested."""
        return self._event.wait(timeout)
