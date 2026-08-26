from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolLoopProgressGuardConfig:
    """Conservative thresholds for detecting a non-progressing tool loop."""

    max_consecutive_duplicates: int = 4
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        if self.max_consecutive_duplicates <= 0:
            raise ValueError("max_consecutive_duplicates must be > 0")
        if self.max_consecutive_failures <= 0:
            raise ValueError("max_consecutive_failures must be > 0")


class ToolLoopProgressGuard:
    """Detect repeated tool-loop behavior without guessing about workspace state.

    The guard intentionally uses only execution facts already available in
    telemetry. It stops a loop after repeated exact duplicates or repeated
    failures; successful, distinct work resets the corresponding streaks.
    This avoids false positives for legitimate exploration and verification.
    """

    def __init__(self, config: ToolLoopProgressGuardConfig | None = None) -> None:
        self.config = config or ToolLoopProgressGuardConfig()
        self.consecutive_duplicates = 0
        self.consecutive_failures = 0
        self.trip_reason: str | None = None

    def record(
        self,
        *,
        tool_name: str,
        status: str,
        duplicate_of: str | None,
        retry_of: str | None,
    ) -> str | None:
        if self.trip_reason is not None:
            return self.trip_reason

        if duplicate_of is not None:
            self.consecutive_duplicates += 1
        else:
            self.consecutive_duplicates = 0

        if status != "completed":
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

        if self.consecutive_duplicates >= self.config.max_consecutive_duplicates:
            self.trip_reason = (
                "tool_loop_progress_guard: repeated exact tool call without progress "
                f"({self.consecutive_duplicates} consecutive duplicates; tool={tool_name})"
            )
        elif self.consecutive_failures >= self.config.max_consecutive_failures:
            self.trip_reason = (
                "tool_loop_progress_guard: repeated tool failures without progress "
                f"({self.consecutive_failures} consecutive failures; tool={tool_name})"
            )
        return self.trip_reason

    def reset(self) -> None:
        self.consecutive_duplicates = 0
        self.consecutive_failures = 0
        self.trip_reason = None
