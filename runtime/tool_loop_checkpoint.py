from __future__ import annotations

from collections import Counter
from typing import Any

DEFAULT_CHECKPOINT_INTERVAL = 4
CHECKPOINT_MARKER = "TOOL LOOP CHECKPOINT"


def build_tool_loop_checkpoint(telemetry: list[dict[str, Any]], *, changed_files: list[str] | None = None, command_results: list[dict[str, Any]] | None = None, workspace_revision: int = 0) -> str | None:
    """Build a compact task-local checkpoint without copying full tool output."""
    if not telemetry:
        return None
    categories = Counter(item.get("category") or "unknown" for item in telemetry)
    duplicates = sum(1 for item in telemetry if item.get("duplicate_of") is not None)
    retries = sum(1 for item in telemetry if item.get("retry_of") is not None)
    duplicate_ratio = duplicates / len(telemetry)
    recent = telemetry[-3:]
    lines = [
        CHECKPOINT_MARKER,
        f"workspace_revision={workspace_revision}",
        f"calls={len(telemetry)} duplicates={duplicates} retries={retries}",
        f"duplicate_ratio={duplicate_ratio:.3f}",
        "categories=" + ", ".join(f"{key}:{value}" for key, value in sorted(categories.items())),
        "recent_tools=" + ", ".join(str(item.get("tool_name") or "unknown") for item in recent),
    ]
    recent_duplicates = [str(item.get("tool_name") or "unknown") for item in recent if item.get("duplicate_of") is not None]
    if recent_duplicates:
        lines.append("recent_duplicate_tools=" + ", ".join(recent_duplicates))
    recent_actions = []
    recent_evidence = []
    for item in recent:
        execution_id = str(item.get("execution_id") or "unknown")
        tool_name = str(item.get("tool_name") or "unknown")
        arguments_hash = str(item.get("arguments_hash") or "unknown")
        result_hash = str(item.get("result_hash") or "unknown")
        result_chars = int(item.get("result_chars", 0) or 0)
        retained_chars = int(item.get("retained_result_chars", result_chars) or 0)
        truncated = bool(item.get("result_truncated"))
        duplicate_of = item.get("duplicate_of")
        retry_of = item.get("retry_of")
        state = "duplicate" if duplicate_of else "retry" if retry_of else "fresh"
        recent_actions.append(f"{execution_id}:{tool_name}:{arguments_hash}:{state}")
        recent_evidence.append(f"{execution_id}:{result_hash}:chars={result_chars}:retained={retained_chars}:truncated={str(truncated).lower()}:revision={workspace_revision}")
    lines.append("recent_actions=" + " | ".join(recent_actions))
    lines.append("recent_evidence=" + " | ".join(recent_evidence))
    if changed_files:
        lines.append("changed_files=" + ", ".join(list(dict.fromkeys(changed_files))[-8:]))
    if command_results:
        lines.append(f"test_or_command_results={len(command_results)}")
        last_command = command_results[-1]
        if isinstance(last_command, dict) and last_command.get("command"):
            lines.append("last_command=" + str(last_command["command"]))
    lines.append(f"verification_calls={categories.get('verification', 0)} execution_calls={categories.get('execution', 0)}")
    lines.extend([
        "Use this checkpoint to continue from the current state.",
        "Recent action/evidence identities reference existing execution history; they do not replace full tool results.",
        "Do not repeat exploration that is already established unless new evidence requires it.",
        "If a verification command already has a recorded result and no relevant file changed afterward, prefer that evidence instead of rerunning the same verification.",
        "If workspace state changed after the recorded evidence, treat the old evidence as stale and re-read or re-verify before relying on it.",
        "Prefer the smallest next action that produces new evidence or completes verification.",
    ])
    if duplicate_ratio >= 0.25:
        lines.append("Duplicate-call rate is elevated: avoid repeating already answered read-only calls unless workspace state changed.")
    return "\n".join(lines)


def upsert_tool_loop_checkpoint(messages: list[dict[str, Any]], telemetry: list[dict[str, Any]], *, changed_files: list[str] | None = None, command_results: list[dict[str, Any]] | None = None, workspace_revision: int = 0) -> bool:
    checkpoint = build_tool_loop_checkpoint(telemetry, changed_files=changed_files, command_results=command_results, workspace_revision=workspace_revision)
    if not checkpoint:
        return False
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, dict) and message.get("role") == "user" and isinstance(message.get("content"), str) and message["content"].startswith(CHECKPOINT_MARKER):
            messages[index] = {"role": "user", "content": checkpoint}
            return True
    messages.append({"role": "user", "content": checkpoint})
    return True


def collapse_tool_loop_checkpoints(messages: list[dict[str, Any]]) -> int:
    checkpoint_indexes = [index for index, message in enumerate(messages) if isinstance(message, dict) and message.get("role") == "user" and isinstance(message.get("content"), str) and message["content"].startswith(CHECKPOINT_MARKER)]
    if len(checkpoint_indexes) <= 1:
        return 0
    stale_indexes = set(checkpoint_indexes[:-1])
    messages[:] = [message for index, message in enumerate(messages) if index not in stale_indexes]
    return len(stale_indexes)
