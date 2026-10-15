from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from time import monotonic
from typing import Any, Callable


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    severity: AlertSeverity
    message: str
    condition: Callable[[Any], bool]
    cooldown_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must be non-empty")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")


@dataclass(frozen=True)
class Alert:
    rule_id: str
    severity: AlertSeverity
    message: str
    dedup_key: str


class AlertManager:
    """Provider-independent alert evaluator with deterministic dedup/cooldown."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or monotonic
        self._rules: dict[str, AlertRule] = {}
        self._last_emitted: dict[tuple[str, str], float] = {}
        self._lock = RLock()

    def register(self, rule: AlertRule) -> None:
        with self._lock:
            if rule.rule_id in self._rules:
                raise ValueError(f"alert rule already registered: {rule.rule_id}")
            self._rules[rule.rule_id] = rule

    def evaluate(self, snapshot: Any, *, dedup_key: str = "global") -> tuple[Alert, ...]:
        if not isinstance(dedup_key, str) or not dedup_key.strip():
            raise ValueError("dedup_key must be a non-empty string")
        now = self._clock()
        emitted: list[Alert] = []
        with self._lock:
            for rule in self._rules.values():
                if not rule.condition(snapshot):
                    continue
                key = (rule.rule_id, dedup_key)
                previous = self._last_emitted.get(key)
                if previous is not None and now - previous < rule.cooldown_seconds:
                    continue
                self._last_emitted[key] = now
                emitted.append(Alert(rule.rule_id, rule.severity, rule.message, dedup_key))
        return tuple(emitted)

    def reset(self) -> None:
        with self._lock:
            self._last_emitted.clear()
