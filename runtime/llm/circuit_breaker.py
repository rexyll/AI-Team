from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runtime.model_governance import ModelRoute


class CircuitBreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class RouteCircuitBreakerConfig:
    """Conservative defaults for provider route health tracking.

    ``failure_threshold`` consecutive provider failures open the circuit;
    ``recovery_timeout_s`` is the cooldown after which one probe request is
    allowed through (half-open). Success closes the circuit, any further
    failure re-opens it immediately.
    """

    failure_threshold: int = 3
    recovery_timeout_s: float = 30.0

    def __post_init__(self) -> None:
        if isinstance(self.failure_threshold, bool) or not isinstance(self.failure_threshold, int):
            raise TypeError("failure_threshold must be an integer")
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if isinstance(self.recovery_timeout_s, bool) or not isinstance(self.recovery_timeout_s, (int, float)):
            raise TypeError("recovery_timeout_s must be a number")
        if self.recovery_timeout_s <= 0:
            raise ValueError("recovery_timeout_s must be > 0")


@dataclass
class _RouteState:
    failures: int = 0
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    opened_at: float = 0.0
    last_error_type: str | None = None
    last_error_message: str | None = None
    total_failures: int = 0
    total_successes: int = 0
    total_rejections: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class RouteCircuitBreaker:
    """Thread-safe per-route circuit breaker for the LLM gateway layer.

    The breaker is a health-tracking policy object, not an execution boundary:
    it never calls providers itself. ``is_healthy`` feeds the governed LLM's
    primary-route health signal, and record calls arrive from the governed LLM
    after actual provider execution.
    """

    def __init__(
        self,
        *,
        config: RouteCircuitBreakerConfig | None = None,
        clock: Any = None,
        max_events_per_route: int = 32,
    ) -> None:
        if config is None:
            config = RouteCircuitBreakerConfig()
        if not isinstance(config, RouteCircuitBreakerConfig):
            raise TypeError("config must be a RouteCircuitBreakerConfig or None")
        if isinstance(max_events_per_route, bool) or not isinstance(max_events_per_route, int):
            raise TypeError("max_events_per_route must be an integer")
        if max_events_per_route < 1:
            raise ValueError("max_events_per_route must be >= 1")
        self.config = config
        self._clock = clock if clock is not None else time.monotonic
        self._max_events = max_events_per_route
        self._routes: dict[ModelRoute, _RouteState] = {}
        self._lock = threading.RLock()

    def _state_for(self, route: ModelRoute) -> _RouteState:
        if not isinstance(route, ModelRoute):
            raise TypeError("route must be a ModelRoute")
        state = self._routes.get(route)
        if state is None:
            state = _RouteState()
            self._routes[route] = state
        return state

    def _append_event(self, state: _RouteState, event: str, detail: str | None = None) -> None:
        state.events.append({"event": event, "at": self._clock(), "detail": detail})
        del state.events[:-self._max_events]

    @staticmethod
    def _error_of(exc: BaseException | None) -> tuple[str | None, str | None]:
        if exc is None:
            return None, None
        return type(exc).__name__, str(exc)[:300]

    def is_healthy(self, route: ModelRoute) -> bool:
        """Return whether the route may carry the next request.

        An open circuit becomes half-open after the recovery cooldown, which
        admits one probe request; the probe's outcome decides the final state.
        """
        with self._lock:
            state = self._state_for(route)
            if state.state == CircuitBreakerState.CLOSED:
                return True
            elapsed = self._clock() - state.opened_at
            if elapsed < self.config.recovery_timeout_s:
                state.total_rejections += 1
                return False
            if state.state != CircuitBreakerState.HALF_OPEN:
                state.state = CircuitBreakerState.HALF_OPEN
                self._append_event(state, "half_open")
            return True

    def record_success(self, route: ModelRoute) -> None:
        with self._lock:
            state = self._state_for(route)
            was_open = state.state != CircuitBreakerState.CLOSED
            state.failures = 0
            state.state = CircuitBreakerState.CLOSED
            state.last_error_type = None
            state.last_error_message = None
            state.total_successes += 1
            if was_open:
                self._append_event(state, "closed")

    def record_failure(self, route: ModelRoute, exc: BaseException | None = None) -> None:
        with self._lock:
            state = self._state_for(route)
            error_type, error_message = self._error_of(exc)
            state.failures += 1
            state.total_failures += 1
            state.last_error_type = error_type
            state.last_error_message = error_message
            half_open_probe = state.state == CircuitBreakerState.HALF_OPEN
            if half_open_probe or state.failures >= self.config.failure_threshold:
                state.state = CircuitBreakerState.OPEN
                state.opened_at = self._clock()
                self._append_event(state, "open", error_type)

    def state_of(self, route: ModelRoute) -> CircuitBreakerState:
        with self._lock:
            return self._state_for(route).state

    def snapshot(self, route: ModelRoute | None = None) -> dict[str, Any]:
        """Return a detached, provider-independent telemetry snapshot."""
        with self._lock:
            if route is not None:
                if not isinstance(route, ModelRoute):
                    raise TypeError("route must be a ModelRoute")
                states = [(route, self._routes.get(route))]
            else:
                states = list(self._routes.items())
            payload: dict[str, Any] = {}
            for key, state in states:
                if state is None:
                    continue
                payload[f"{key.provider}/{key.model}"] = {
                    "state": state.state.value,
                    "consecutive_failures": state.failures,
                    "total_failures": state.total_failures,
                    "total_successes": state.total_successes,
                    "total_rejections": state.total_rejections,
                    "last_error_type": state.last_error_type,
                    "last_error_message": state.last_error_message,
                    "recent_events": list(state.events),
                }
            return payload
