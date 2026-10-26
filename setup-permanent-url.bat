@echo off
REM Double-click to give your API a permanent URL using your own Cloudflare account.
REM   setup-permanent-url.bat           set or change the tunnel token and hostname
REM   setup-permanent-url.bat -Remove   go back to the free random quick-tunnel URL
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-tunnel.ps1" %*
pause
