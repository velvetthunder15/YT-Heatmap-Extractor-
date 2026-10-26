@echo off
REM Double-click for a permanent API URL on your own Cloudflare account (free workers.dev, or your domain).
REM   setup-permanent-url.bat           set it up or change it
REM   setup-permanent-url.bat -Remove   go back to the free random quick-tunnel URL
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-tunnel.ps1" %*
pause
