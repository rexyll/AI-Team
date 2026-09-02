# Local MCP Bridge Security — Phase 0-2

## Active controls

1. Explicit absolute workspace root.
2. Canonical path resolution by `WorkspaceSandbox`.
3. Parent/absolute/symlink escapes rejected as `PermissionError`.
4. Direct `.git` metadata access denied.
5. No arbitrary shell execution.
6. No write tools.
7. No Git write tools.
8. No host absolute path returned by the diagnostic path tool.
9. MCP application logs go to stderr, not the stdio protocol channel.

## Deferred controls

The following are deliberately deferred until their planned phases:

- patch concurrency/hash validation
- command allowlists
- test process timeout/output limits
- Git staging/commit confirmation
- MCP audit persistence
- search/read size limits
- Windows junction-specific regression on a Windows runner

These are not claimed as completed in Phase 0-2.
