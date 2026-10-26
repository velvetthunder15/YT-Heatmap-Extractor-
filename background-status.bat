@echo off
REM Show whether the background API is running, and its URL and key.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\background-install.ps1" status
pause
