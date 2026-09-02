# AI-Team Local MCP Bridge Architecture — Phase 3

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

## Phase 3 public MCP surface

The bridge exposes five read-only tools:

- `bridge_health`
- `workspace_validate_path`
- `workspace_list_files`
- `workspace_read_file`
- `workspace_search_text`

No source-code write, shell execution, Git write, network operation, or file
deletion is enabled in this phase.

## Read-only workspace policy

All workspace access crosses `MCPWorkspaceBoundary`, which delegates path
containment to the canonical `security.workspace.WorkspaceSandbox`.

The adapter additionally denies direct `.git` access and hides host absolute
paths from tool results. File reads are bounded by `max_bytes`; directory
listing and text search have explicit result limits.

The search implementation is intentionally literal substring matching rather
than a shell command or regular-expression engine. This keeps the first MCP
read surface deterministic and avoids turning search into an execution path.

Ignored implementation directories (`.git`, `.venv`, caches, IDE metadata) are
not returned or searched.

## stdio safety

The MCP protocol uses stdout for stdio transport. Application logging is
therefore configured on stderr only.

## Next extension boundary

Write operations must not be added by directly calling `tools.filesystem`.
The next write phase should introduce an explicit host-owned MCP mutation
adapter with authorization, audit, tracing, and bounded payload semantics.
Terminal and Git mutation should remain separate capability boundaries.
