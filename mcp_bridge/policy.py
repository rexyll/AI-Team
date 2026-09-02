from __future__ import annotations

from dataclasses import dataclass


POLICY_PROFILE_ENV = "AI_TEAM_MCP_POLICY_PROFILE"
DEFAULT_POLICY_PROFILE = "developer"
VALID_POLICY_PROFILES = frozenset({"readonly", "developer", "production"})


@dataclass(frozen=True)
class MCPPolicy:
    """Single capability policy used by every MCP adapter.

    The policy gates MCP exposure only. Canonical workspace, Git, terminal,
    and orchestration boundaries remain responsible for their domain-specific
    validation and enforcement.
    """

    profile: str
    workspace_write: bool
    git_write: bool
    terminal: bool
    workflow_execute: bool

    @classmethod
    def from_profile(cls, profile: str = DEFAULT_POLICY_PROFILE) -> "MCPPolicy":
        normalized = profile.strip().lower() if isinstance(profile, str) else ""
        if normalized not in VALID_POLICY_PROFILES:
            allowed = ", ".join(sorted(VALID_POLICY_PROFILES))
            raise ValueError(f"policy profile must be one of: {allowed}")
        if normalized in {"readonly", "production"}:
            return cls(
                profile=normalized,
                workspace_write=False,
                git_write=False,
                terminal=False,
                workflow_execute=False,
            )
        return cls(
            profile=normalized,
            workspace_write=True,
            git_write=True,
            terminal=True,
            workflow_execute=True,
        )

    def allows(self, capability: str) -> bool:
        values = {
            "workspace_write": self.workspace_write,
            "git_write": self.git_write,
            "terminal": self.terminal,
            "workflow_execute": self.workflow_execute,
        }
        try:
            return values[capability]
        except KeyError as exc:
            raise ValueError(f"unknown MCP capability: {capability}") from exc
