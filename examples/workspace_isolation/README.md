# Workspace isolation example

This example demonstrates that two project sandboxes can use identical relative paths without sharing files.

Run from the repository root:

```powershell
python examples/workspace_isolation/run.py
```

Expected output:

```text
workspace-a=project-a
workspace-b=project-b
cross-workspace-access=blocked
```

The example uses the production `security.workspace.WorkspaceSandbox` contract. It does not modify the global default workspace, require an API key, or access the network.

The important property is containment: a path resolved by one sandbox cannot be used to access a file rooted in another sandbox. Each project can therefore have its own `src/result.txt` without collision.
