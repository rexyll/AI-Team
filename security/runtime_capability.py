from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from security.tool_permission import EXECUTE, READ, WRITE, ToolPermissionError


TOOL_CAPABILITIES: dict[str, frozenset[str]] = {
    "list_files": frozenset({READ}),
    "read_file": frozenset({READ}),
    "write_file": frozenset({WRITE}),
    "move_file": frozenset({WRITE}),
    "delete_file": frozenset({WRITE}),
    "run_command": frozenset({EXECUTE}),
    # Kept as an explicit policy marker for the legacy low-level helper.
    # It is deliberately excluded from agent-visible filtering below.
    "git_command": frozenset({EXECUTE, WRITE}),
}

# Raw Git command execution is a host-owned primitive. Agents/plugins must
# use semantic host APIs rather than receiving an arbitrary command surface.
HOST_ONLY_TOOLS = frozenset({"git_command"})

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "architect": frozenset({READ}),
    "developer": frozenset({READ, WRITE, EXECUTE}),
    "tester": frozenset({READ, EXECUTE}),
    "reviewer": frozenset({READ}),
    "planner": frozenset(),
    # The analyst works purely on the LLM level and holds no tool surface.
    "analyst": frozenset(),
    # The documentation writer reads project context and writes documents,
    # but never executes commands in the workspace.
    "doc_writer": frozenset({READ, WRITE}),
}


@dataclass(frozen=True)
class RuntimeCapabilityPolicy:
    """Deny-by-default authorization for agent -> tool capability use."""

    role_capabilities: dict[str, frozenset[str]]

    def __init__(self, role_capabilities: dict[str, Iterable[str]] | None = None) -> None:
        grants = role_capabilities or ROLE_CAPABILITIES
        normalized = {role: frozenset(capabilities) for role, capabilities in grants.items()}
        object.__setattr__(self, "role_capabilities", normalized)

    def required_capabilities(self, tool_name: str) -> frozenset[str]:
        if tool_name not in TOOL_CAPABILITIES:
            raise KeyError(f"Unknown tool capability mapping: {tool_name}")
        return TOOL_CAPABILITIES[tool_name]

    def allows(self, role: str, tool_name: str) -> bool:
        if tool_name in HOST_ONLY_TOOLS:
            return False
        required = self.required_capabilities(tool_name)
        granted = self.role_capabilities.get(role, frozenset())
        return required.issubset(granted)

    def require(self, role: str, tool_name: str) -> None:
        if tool_name in HOST_ONLY_TOOLS:
            raise ToolPermissionError(
                f"Tool {tool_name!r} is host-only and cannot be invoked by agent role {role!r}"
            )
        if not self.allows(role, tool_name):
            raise ToolPermissionError(
                f"Agent role {role!r} is not authorized to use tool {tool_name!r}"
            )

    def filter_tool_names(self, role: str, tool_names: Iterable[str]) -> list[str]:
        return [
            name
            for name in tool_names
            if name not in HOST_ONLY_TOOLS
            and name in TOOL_CAPABILITIES
            and self.allows(role, name)
        ]


DEFAULT_RUNTIME_CAPABILITY_POLICY = RuntimeCapabilityPolicy()
