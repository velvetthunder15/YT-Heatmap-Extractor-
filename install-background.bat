@echo off
REM Run the API hidden in the background, now and at every login (no window to keep open).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\background-install.ps1" install
pause
