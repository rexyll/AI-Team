# Developer Workspace Isolation

## Status

The first isolation milestone is implemented in `runtime/developer_workspace.py` and integrated into `core/orchestrator.py`.

It provides per-Developer task snapshots, task-local filesystem sandbox context, cross-process merge serialization, conflict detection, and abandoned-lease cleanup. It is not yet a full container/OS sandbox and does not make a multi-file merge globally atomic.

## Lifecycle

1. The project orchestrator places the canonical deliverable root in each Developer task's internal context.
2. The orchestrator obtains a `DeveloperWorkspaceManager` for that root and calls `issue(task_id)`.
3. The manager acquires a thread lock and an OS-level process lock scoped to the canonical root.
4. The manager copies managed source files into a unique sibling lease directory. Mutable/generated directories such as `.venv`, `venv`, `node_modules`, `.git`, bytecode and tool caches are excluded.
5. A sidecar `<lease-name>.lease.json` is atomically written before the lease is returned. It records the schema version, lease ID, task ID, owner PID and creation time.
6. `workspace_scope()` binds filesystem tools to the lease root using `ContextVar`. Concurrent tool calls copy the current context before dispatch, so they retain the correct task-local root.
7. If the workflow completes, `merge(lease)` compares SHA-256 snapshots and applies only paths changed by this task. If the canonical workspace changed the same path to different content, merge raises `WorkspaceMergeConflict` and does not overwrite that path.
8. Failed or exceptional workflows discard their lease in a `finally` block. The lease is removed after a successful merge as well.

## Cross-process coordination and crash recovery

The manager uses the existing `runtime.process_lock.exclusive_process_lock` implementation. Managers targeting the same canonical root share a lock file, so snapshot creation, merge validation/application and cleanup are serialized across processes as well as threads.

On manager initialization and before issuing another lease, stale recovery scans the lease directory:

- A lease directory without metadata is treated as an incomplete issue operation. The manager lock ensures another process cannot observe it while it is being created.
- A valid lease whose owner PID is confirmed dead is removed.
- A lease whose owner PID is still alive is preserved.
- Corrupt or unknown metadata is preserved for inspection; recovery fails safe rather than guessing that the owner is dead.
- PID reuse can conservatively leave an abandoned lease behind. This favors avoiding deletion of a live workspace over aggressive cleanup.

The manager does not adopt another process's lease for merging. A merge/discard operation must be performed by the PID recorded as the lease owner.

## Path and merge safety

- Task IDs are restricted to a bounded safe character set.
- Lease roots must be direct children of the manager-owned lease directory.
- Symbolic links in the managed canonical tree or developer lease are rejected.
- Relative merge paths reject absolute paths and parent traversal.
- Every canonical destination path is checked for symlink components and resolved containment before writes.
- File replacement uses a temporary file in the destination directory followed by `os.replace`.
- A same-path divergent change fails closed. Disjoint file changes can merge independently.

The lock coordinates AI-Team managers. It does not prevent an unrelated process or user from changing the canonical tree outside this lock. The current merge is atomic per file, not transactional across the entire set of files; an OS/process failure during a multi-file merge can leave a partial set of already-replaced files. A durable merge journal/rollback protocol is a remaining hardening item.

## Dependency directory policy

Virtual environments, package installation trees and generated caches are deliberately not copied or merged. Sharing mutable `.venv` or `node_modules` across parallel Developers would reintroduce cross-task write races and could allow one task to alter another task's execution environment.

The corresponding trade-off is that a task lease does not inherit those directories. Project adapters must provision isolated task-local environments or explicitly provide a verified read-only dependency cache. The current implementation does not claim that dependency setup is solved.

## Current boundaries

This is task-level filesystem isolation for the AI-Team tool sandbox. It is not equivalent to a separate OS user, container, VM, seccomp profile or network namespace. Shell commands still rely on the existing terminal allowlist, process controls and workspace-root behavior. Production-grade hostile-code isolation requires a stronger execution backend.

## Verification

The contract suite covers:

- successful/failed/exceptional Developer workflows;
- changed, added and deleted files;
- same-path conflict and disjoint parallel merges;
- independent manager processes attempting competing merges;
- simulated stale PID recovery and preservation of live leases;
- real owner-process termination and subsequent recovery;
- symlink/path traversal rejection;
- dependency-directory exclusion and non-merging;
- context propagation and folded output-path compatibility.

The latest successful regression evidence is recorded in `TaskPlan.md`. The actual-process-termination test is being validated in CI before this milestone is considered complete.
