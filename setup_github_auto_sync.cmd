@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_github_auto_sync.ps1" %*
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" pause
endlocal & exit /b %EXIT_CODE%