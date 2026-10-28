@echo off
REM Double-click to run the Heatmapify on Windows (no Docker, no WSL).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local-windows.ps1" %*
pause
