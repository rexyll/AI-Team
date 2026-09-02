# AI-Team Local MCP Bridge Architecture — Phase 4

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
   +-- read adapter policy
   +-- mutation adapter policy
   |
   +------------------------------+
   |                              |
   v                              v
MCPWorkspaceBoundary      MCPWorkspaceMutationBoundary
   |                              |
   +--------------+---------------+
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

## Phase 4 public MCP surface

The bridge exposes seven tools:

- `bridge_health`
- `workspace_validate_path`
- `workspace_list_files`
- `workspace_read_file`
- `workspace_search_text`
- `workspace_write_file`
- `workspace_delete_file`

Read operations remain bounded and deterministic. Mutation operations are
explicitly separated from the generic `tools.filesystem` implementation.

## Workspace mutation policy

All mutations cross `MCPWorkspaceMutationBoundary`, which delegates path
containment to `MCPWorkspaceBoundary` and therefore to the canonical
`security.workspace.WorkspaceSandbox`.

The mutation adapter additionally:

- rejects `.git`, `.venv`, caches, and IDE metadata;
- rejects paths outside the authorized workspace;
- accepts UTF-8 text only;
- enforces a configurable per-write byte limit capped at 8 MiB;
- creates parent directories only after validating the canonical parent path;
- refuses to overwrite an existing file unless `overwrite=true` is explicit;
- allows deletion only for regular files;
- returns relative paths only; and
- emits an audit event only after a successful mutation.

The adapter never invokes a shell, Git command, network request, or generic
filesystem tool.

## Audit and tracing boundary

`WorkspaceMutationEvent` is the host-owned mutation event contract. The
mutation boundary accepts an audit sink callback and emits `create`, `update`,
or `delete` events only after the corresponding filesystem operation succeeds.

The MCP server also logs successful mutations through the existing stderr-only
application logger. The event payload contains only the relative path,
operation, and byte count; no host absolute path or file contents are emitted.

A later production phase can route this event contract into the canonical
runtime audit/tracing pipeline without changing the MCP authorization model.

## Error behavior

The MCP SDK may normalize server-side exceptions into a generic tool error at
the protocol boundary. Security and validation behavior therefore remains
asserted at the `MCPWorkspaceMutationBoundary` unit level, while MCP client
contract tests assert `is_error=true` for rejected operations.

## stdio safety

The MCP protocol uses stdout for stdio transport. Application logging is
therefore configured on stderr only.

## Next extension boundary

Git read and mutation must not be added to the workspace adapter. The next
phase should introduce an explicit host-owned Git boundary with allowlisted
operations, structured results, authorization, audit/tracing, and no direct
`.git` access. Terminal execution remains a separate capability boundary.
