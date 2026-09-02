@echo off
setlocal
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo AI-Team virtualenv Python not found: %PYTHON% 1>&2
  exit /b 1
)

set "AI_TEAM_WORKSPACE=%REPO_ROOT%"
if "%AI_TEAM_MCP_LOG_LEVEL%"=="" set "AI_TEAM_MCP_LOG_LEVEL=INFO"

cd /d "%REPO_ROOT%"
"%PYTHON%" -m mcp_bridge.server
exit /b %ERRORLEVEL%
