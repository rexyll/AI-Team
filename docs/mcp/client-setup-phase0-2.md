# Local deployment — Phase 0-2

## 1. Install

From the AI-Team repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-mcp.txt
```

## 2. Configure

```powershell
$env:AI_TEAM_WORKSPACE = (Get-Location).Path
$env:AI_TEAM_MCP_LOG_LEVEL = "INFO"
```

`AI_TEAM_WORKSPACE` must be the absolute repository root.

## 3. Test

```powershell
pytest tests/mcp -q
pytest -q
```

The first command validates the new bridge contract. The second is the required
AI-Team full regression before accepting the phase.

## 4. Run with MCP Inspector

The MCP Inspector requires `npx` on PATH:

```powershell
mcp dev mcp_bridge/server.py
```

## 5. Run as a stdio MCP server

```powershell
python -m mcp_bridge.server
```

A stdio MCP server normally appears to do nothing when launched manually: it is
waiting for its MCP host to send requests on stdin.

## Generic stdio client configuration

Use the absolute path to the venv Python executable and repository root.

```json
{
  "command": "F:\\workspace\\_coding_workspace\\AI-Team\\ai-dev-team\\.venv\\Scripts\\python.exe",
  "args": ["-m", "mcp_bridge.server"],
  "cwd": "F:\\workspace\\_coding_workspace\\AI-Team\\ai-dev-team",
  "env": {
    "AI_TEAM_WORKSPACE": "F:\\workspace\\_coding_workspace\\AI-Team\\ai-dev-team",
    "AI_TEAM_MCP_LOG_LEVEL": "INFO"
  }
}
```

The exact outer JSON shape differs by MCP host; the command/args/cwd/env values
remain the same.
