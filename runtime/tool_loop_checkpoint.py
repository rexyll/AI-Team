from __future__ import annotations

from collections import Counter
from typing import Any


DEFAULT_CHECKPOINT_INTERVAL = 4


def build_tool_loop_checkpoint(
    telemetry: list[dict[str, Any]],
    *,
    changed_files: list[str] | None = None,
    command_results: list[dict[str, Any]] | None = None,
) -> str | None:
    """Build a compact decision checkpoint for long developer tool loops.

    The checkpoint contains only decision-relevant counters and recent state.
    Full tool output remains in the execution history and is deliberately not
    copied into the next LLM prompt. The checkpoint also exposes lightweight
    verification state so the model can avoid unnecessary repeated test turns.
    """
    if not telemetry:
        return None

    categories = Counter(item.get("category") or "unknown" for item in telemetry)
    duplicates = sum(1 for item in telemetry if item.get("duplicate_of") is not None)
    retries = sum(1 for item in telemetry if item.get("retry_of") is not None)
    recent = telemetry[-3:]
    recent_tools = [str(item.get("tool_name") or "unknown") for item in recent]

    lines = [
        "TOOL LOOP CHECKPOINT",
        f"calls={len(telemetry)} duplicates={duplicates} retries={retries}",
        "categories=" + ", ".join(f"{key}:{value}" for key, value in sorted(categories.items())),
        "recent_tools=" + ", ".join(recent_tools),
    ]
    if changed_files:
        unique_changed_files = list(dict.fromkeys(changed_files))
        lines.append("changed_files=" + ", ".join(unique_changed_files[-8:]))
    if command_results:
        lines.append(f"test_or_command_results={len(command_results)}")
        last_command = command_results[-1]
        if isinstance(last_command, dict) and last_command.get("command"):
            lines.append("last_command=" + str(last_command["command"]))

    verification_count = categories.get("verification", 0)
    execution_count = categories.get("execution", 0)
    lines.append(f"verification_calls={verification_count} execution_calls={execution_count}")

    lines.extend(
        [
            "Use this checkpoint to continue from the current state.",
            "Do not repeat exploration that is already established unless new evidence requires it.",
            "If a verification command already has a recorded result and no relevant file changed afterward, prefer using that evidence instead of rerunning the same verification.",
            "Prefer the smallest next action that produces new evidence or completes verification.",
        ]
    )
    return "\n".join(lines)
