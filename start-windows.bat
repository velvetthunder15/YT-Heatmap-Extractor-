@echo off
REM Double-click to run the YouTube Heatmap Extractor on Windows (no Docker, no WSL).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local-windows.ps1" %*
pause
