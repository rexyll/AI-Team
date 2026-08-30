from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from time import monotonic
from typing import Iterator, Mapping


class MetricsRegistry:
    """Small thread-safe in-process metrics registry.

    Metrics are intentionally provider-independent. Exporters can consume
    ``snapshot()`` without coupling workflow code to Prometheus or another
    monitoring backend.
    """

    def __init__(self) -> None:
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
        self._gauges: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
        self._histograms: dict[str, dict[tuple[tuple[str, str], ...], list[float]]] = defaultdict(dict)
        self._lock = threading.RLock()

    @staticmethod
    def _key(labels: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
        if labels is None:
            return ()
        if not isinstance(labels, Mapping):
            raise TypeError("labels must be a mapping or None")
        result = []
        for key, value in labels.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("metric label names must be non-empty strings")
            result.append((key.strip(), str(value)))
        return tuple(sorted(result))

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric name must be a non-empty string")
        return name.strip()

    def inc(self, name: str, value: float = 1, *, labels: Mapping[str, object] | None = None) -> float:
        name = self._name(name)
        if value < 0:
            raise ValueError("counter increment must be non-negative")
        key = self._key(labels)
        with self._lock:
            current = self._counters[name].get(key, 0.0) + float(value)
            self._counters[name][key] = current
            return current

    def set_gauge(self, name: str, value: float, *, labels: Mapping[str, object] | None = None) -> float:
        name = self._name(name)
        key = self._key(labels)
        with self._lock:
            self._gauges[name][key] = float(value)
            return float(value)

    def observe(self, name: str, value: float, *, labels: Mapping[str, object] | None = None) -> float:
        name = self._name(name)
        key = self._key(labels)
        with self._lock:
            self._histograms[name].setdefault(key, []).append(float(value))
            return float(value)

    @contextmanager
    def time(self, name: str, *, labels: Mapping[str, object] | None = None) -> Iterator[None]:
        started = monotonic()
        try:
            yield
        finally:
            self.observe(name, monotonic() - started, labels=labels)

    def snapshot(self) -> dict[str, dict[str, list[dict[str, object]]]]:
        """Return a detached, JSON-friendly snapshot of all metric values."""
        with self._lock:
            return {
                "counters": self._snapshot_values(self._counters),
                "gauges": self._snapshot_values(self._gauges),
                "histograms": self._snapshot_histograms(),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()

    @staticmethod
    def _snapshot_values(source: Mapping[str, Mapping[tuple[tuple[str, str], ...], float]]) -> dict[str, list[dict[str, object]]]:
        return {
            name: [
                {"labels": dict(labels), "value": value}
                for labels, value in sorted(values.items())
            ]
            for name, values in sorted(source.items())
        }

    def _snapshot_histograms(self) -> dict[str, list[dict[str, object]]]:
        return {
            name: [
                {
                    "labels": dict(labels),
                    "count": len(values),
                    "sum": sum(values),
                    "min": min(values),
                    "max": max(values),
                }
                for labels, values in sorted(series.items())
                if values
            ]
            for name, series in sorted(self._histograms.items())
        }


DEFAULT_METRICS = MetricsRegistry()
