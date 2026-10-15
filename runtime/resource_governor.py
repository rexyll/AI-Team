from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceLimits:
    """Hard limits for one project execution scope."""

    max_concurrent_tasks: int = 1
    max_tool_calls: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.max_concurrent_tasks, int) or isinstance(self.max_concurrent_tasks, bool):
            raise TypeError("max_concurrent_tasks must be an integer")
        if self.max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be positive")
        for name in ("max_tool_calls", "max_input_tokens", "max_output_tokens"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise TypeError(f"{name} must be an integer or None")
                if value < 0:
                    raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class ResourceUsage:
    """Monotonic project-level resource counters."""

    active_tasks: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class ResourceGovernor:
    """Read-only admission plus immutable accounting for execution resources."""

    def __init__(self, limits: ResourceLimits, usage: ResourceUsage | None = None) -> None:
        if not isinstance(limits, ResourceLimits):
            raise TypeError("limits must be a ResourceLimits")
        if usage is None:
            usage = ResourceUsage()
        if not isinstance(usage, ResourceUsage):
            raise TypeError("usage must be a ResourceUsage")
        if any(value < 0 for value in (usage.active_tasks, usage.tool_calls, usage.input_tokens, usage.output_tokens)):
            raise ValueError("resource usage counters must be non-negative")
        if usage.active_tasks > limits.max_concurrent_tasks:
            raise ValueError("active_tasks exceeds max_concurrent_tasks")
        self._limits = limits
        self._usage = usage

    @property
    def limits(self) -> ResourceLimits:
        return self._limits

    @property
    def usage(self) -> ResourceUsage:
        return self._usage

    def can_start_task(self, slots: int = 1) -> bool:
        if not isinstance(slots, int) or isinstance(slots, bool):
            raise TypeError("slots must be an integer")
        if slots < 1:
            raise ValueError("slots must be positive")
        return self._usage.active_tasks + slots <= self._limits.max_concurrent_tasks

    def can_consume(self, *, tool_calls: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> bool:
        values = {"tool_calls": tool_calls, "input_tokens": input_tokens, "output_tokens": output_tokens}
        for name, value in values.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        checks = (
            ("tool_calls", self._limits.max_tool_calls),
            ("input_tokens", self._limits.max_input_tokens),
            ("output_tokens", self._limits.max_output_tokens),
        )
        for name, limit in checks:
            if limit is not None and getattr(self._usage, name) + values[name] > limit:
                return False
        return True

    def start_task(self, slots: int = 1) -> "ResourceGovernor":
        if not self.can_start_task(slots):
            raise RuntimeError("concurrency resource limit exceeded")
        return ResourceGovernor(
            self._limits,
            ResourceUsage(
                active_tasks=self._usage.active_tasks + slots,
                tool_calls=self._usage.tool_calls,
                input_tokens=self._usage.input_tokens,
                output_tokens=self._usage.output_tokens,
            ),
        )

    def finish_task(self, slots: int = 1) -> "ResourceGovernor":
        if not isinstance(slots, int) or isinstance(slots, bool):
            raise TypeError("slots must be an integer")
        if slots < 1:
            raise ValueError("slots must be positive")
        if slots > self._usage.active_tasks:
            raise RuntimeError("cannot finish more active tasks than currently running")
        return ResourceGovernor(
            self._limits,
            ResourceUsage(
                active_tasks=self._usage.active_tasks - slots,
                tool_calls=self._usage.tool_calls,
                input_tokens=self._usage.input_tokens,
                output_tokens=self._usage.output_tokens,
            ),
        )

    def consume(self, *, tool_calls: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> "ResourceGovernor":
        if not self.can_consume(tool_calls=tool_calls, input_tokens=input_tokens, output_tokens=output_tokens):
            raise RuntimeError("resource budget exceeded")
        return ResourceGovernor(
            self._limits,
            ResourceUsage(
                active_tasks=self._usage.active_tasks,
                tool_calls=self._usage.tool_calls + tool_calls,
                input_tokens=self._usage.input_tokens + input_tokens,
                output_tokens=self._usage.output_tokens + output_tokens,
            ),
        )
