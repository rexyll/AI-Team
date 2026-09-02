$ErrorActionPreference = "Stop"

# The script lives in <repo>/mcp/web_host_bridge/scripts, so the repository
# root is two levels up.
$RepoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot "..") "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "AI-Team virtualenv Python not found: $Python"
}

$env:AI_TEAM_WORKSPACE = $RepoRoot

if (-not $env:AI_TEAM_MCP_LOG_LEVEL) {
    $env:AI_TEAM_MCP_LOG_LEVEL = "INFO"
}

# The bridge package lives under <repo>/mcp; the repository root keeps the
# host-owned runtime/security/tools imports importable.
$env:PYTHONPATH = "$RepoRoot\mcp;$RepoRoot"

Set-Location $RepoRoot
& $Python -m web_host_bridge.server
exit $LASTEXITCODE
