from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolLoopProgressGuardConfig:
    """Conservative thresholds for detecting a non-progressing tool loop."""

    max_consecutive_duplicates: int = 4
    max_consecutive_failures: int = 3
    max_consecutive_stagnant_results: int = 6

    def __post_init__(self) -> None:
        if self.max_consecutive_duplicates <= 0:
            raise ValueError("max_consecutive_duplicates must be > 0")
        if self.max_consecutive_failures <= 0:
            raise ValueError("max_consecutive_failures must be > 0")
        if self.max_consecutive_stagnant_results <= 0:
            raise ValueError("max_consecutive_stagnant_results must be > 0")


class ToolLoopProgressGuard:
    """Detect repeated tool-loop behavior without inspecting the workspace.

    The guard uses execution facts already available in telemetry. In addition
    to exact duplicates and failures, it can detect *stagnant evidence*: several
    consecutive successful calls that produce the same result hash while using
    different arguments. This catches loops such as repeated read-only
    inspection with changing, ineffective queries without treating ordinary
    exploration as a failure.
    """

    def __init__(self, config: ToolLoopProgressGuardConfig | None = None) -> None:
        self.config = config or ToolLoopProgressGuardConfig()
        self.consecutive_duplicates = 0
        self.consecutive_failures = 0
        self.consecutive_stagnant_results = 0
        self._last_result_hash: str | None = None
        self.trip_reason: str | None = None

    def record(
        self,
        *,
        tool_name: str,
        status: str,
        duplicate_of: str | None,
        retry_of: str | None,
        result_hash: str | None = None,
        progress: bool | None = None,
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

        if status == "completed" and result_hash is not None and progress is not True:
            if result_hash == self._last_result_hash:
                self.consecutive_stagnant_results += 1
            else:
                # The current successful result starts a new evidence streak.
                # Counting the baseline call makes a threshold of N mean
                # "N consecutive calls with unchanged evidence".
                self.consecutive_stagnant_results = 1
            self._last_result_hash = result_hash
        else:
            self.consecutive_stagnant_results = 0
            self._last_result_hash = None

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
        elif self.consecutive_stagnant_results >= self.config.max_consecutive_stagnant_results:
            self.trip_reason = (
                "tool_loop_progress_guard: repeated successful calls produced unchanged evidence "
                f"({self.consecutive_stagnant_results} consecutive stagnant results; tool={tool_name})"
            )
        return self.trip_reason

    def reset(self) -> None:
        self.consecutive_duplicates = 0
        self.consecutive_failures = 0
        self.consecutive_stagnant_results = 0
        self._last_result_hash = None
        self.trip_reason = None
