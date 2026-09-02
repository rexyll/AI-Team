$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "AI-Team virtualenv Python not found: $Python"
}

$env:AI_TEAM_WORKSPACE = $RepoRoot

if (-not $env:AI_TEAM_MCP_LOG_LEVEL) {
    $env:AI_TEAM_MCP_LOG_LEVEL = "INFO"
}

Set-Location $RepoRoot
& $Python -m mcp_bridge.server
exit $LASTEXITCODE
