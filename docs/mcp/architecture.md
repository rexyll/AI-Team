# AI-Team Local MCP Bridge Architecture — Phase 0-2

## Purpose

The bridge exposes a deliberately narrow MCP surface over an authorized local
AI-Team repository. It is an adapter, not a second runtime/security system.

```text
MCP Host
   |
   v
mcp_bridge
   |
   +-- configuration
   +-- adapter policy
   |
   v
security.workspace.WorkspaceSandbox
   |
   v
authorized AI-Team repository
```

Git operations in later phases must go through:

```text
runtime.host_git.HostGitOperationService
```

rather than reading or executing commands against `.git` directly.

## Package name

The implementation uses `mcp_bridge/`, not `mcp/`.

The official Python SDK is imported as `mcp`, so a local top-level directory
named `mcp` would shadow the dependency and create fragile imports.

## Phase 0-2 public MCP surface

Only two diagnostic tools are exposed:

- `bridge_health`
- `workspace_validate_path`

No source-code write, shell execution, Git write, network operation, or file
deletion is enabled.

## Workspace configuration

`AI_TEAM_WORKSPACE` is mandatory and must be an absolute, existing directory.
There is intentionally no implicit "current directory" fallback.

## Path authorization

`MCPWorkspaceBoundary` delegates containment to AI-Team's existing
`security.workspace.WorkspaceSandbox`.

The MCP adapter additionally rejects direct `.git` access. Git inspection and
mutation are reserved for the host-owned Git service planned for later phases.

## stdio safety

The MCP protocol uses stdout for stdio transport. Application logging is
therefore configured on stderr only.
