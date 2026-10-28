@echo off
REM Replace your API key, for example if it leaked. The old key stops working once the server restarts.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start-windows.bat once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m scripts.local_setup --rotate-key > "%TEMP%\heatmapify-key.txt" || (echo Could not rotate the key. & pause & exit /b 1)
echo.
echo Your new API key (also saved in secrets\api_key.txt):
type "%TEMP%\heatmapify-key.txt"
del "%TEMP%\heatmapify-key.txt"
echo.
echo Now restart the server (close start-windows.bat and open it again, or sign out and back in if it runs in the background),
echo then paste the new key into the dashboard.
pause
