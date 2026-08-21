from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import FrozenSet


READ = "read"
WRITE = "write"
EXECUTE = "execute"

VALID_CAPABILITIES: FrozenSet[str] = frozenset({READ, WRITE, EXECUTE})


class ToolPermissionError(PermissionError):
    """Raised when a tool is not authorized for a requested capability."""


@dataclass(frozen=True)
class ToolPermissionPolicy:
    """Small deny-by-default capability policy for tool execution.

    The policy answers only whether a tool identity has a capability. It does
    not validate arguments and does not resolve filesystem paths; those remain
    the responsibility of ToolArgumentValidation and WorkspaceSandbox.
    """

    grants: dict[str, FrozenSet[str]]

    def __init__(self, grants: dict[str, Iterable[str]] | None = None) -> None:
        normalized: dict[str, FrozenSet[str]] = {}

        for tool_name, capabilities in (grants or {}).items():
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise TypeError("Tool name must be a non-empty string")

            capability_set = frozenset(capabilities)
            unknown = capability_set - VALID_CAPABILITIES
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ValueError(f"Unknown tool capability(s): {names}")

            normalized[tool_name] = capability_set

        object.__setattr__(self, "grants", normalized)

    def allows(self, tool_name: str, capability: str) -> bool:
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise TypeError("Tool name must be a non-empty string")
        if capability not in VALID_CAPABILITIES:
            raise ValueError(f"Unknown tool capability: {capability!r}")
        return capability in self.grants.get(tool_name, frozenset())

    def require(self, tool_name: str, capability: str) -> None:
        if not self.allows(tool_name, capability):
            raise ToolPermissionError(
                f"Tool {tool_name!r} is not permitted to use capability "
                f"{capability!r}"
            )


DEFAULT_TOOL_PERMISSION_POLICY = ToolPermissionPolicy()
