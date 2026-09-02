@echo off
setlocal
rem The script lives in <repo>/mcp/web_host_bridge/scripts, so the repository
rem root is two levels up.
set "REPO_ROOT=%~dp0..\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo AI-Team virtualenv Python not found: %PYTHON% 1>&2
  exit /b 1
)

set "AI_TEAM_WORKSPACE=%REPO_ROOT%"
if "%AI_TEAM_MCP_LOG_LEVEL%"=="" set "AI_TEAM_MCP_LOG_LEVEL=INFO"

rem The bridge package lives under <repo>/mcp; the repository root keeps the
rem host-owned runtime/security/tools imports importable.
set "PYTHONPATH=%REPO_ROOT%\mcp;%REPO_ROOT%"

cd /d "%REPO_ROOT%"
"%PYTHON%" -m web_host_bridge.server
exit /b %ERRORLEVEL%
