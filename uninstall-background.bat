@echo off
REM Stop the background API and remove it from login.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\background-install.ps1" uninstall
pause
