@echo off
rem Double-clickable entry point for setup-all.ps1. Bypasses the current
rem user's PowerShell execution policy for THIS invocation only (does not
rem change any system/user policy setting) so the script runs even under a
rem default "Restricted"/"AllSigned" policy.
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%setup-all.ps1" %*
set EXIT_CODE=%ERRORLEVEL%
echo.
echo Exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%
