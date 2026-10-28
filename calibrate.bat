@echo off
REM Tune the estimate against YouTubes own "Most replayed" data.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start-windows.bat once first.
  pause
  exit /b 1
)
if not exist calibration mkdir calibration
if not exist calibration\videos.txt (
  echo # Paste YouTube links that HAVE the "Most replayed" graph, one per line. 10 or more works best.> calibration\videos.txt
  echo Add some video links to the file that just opened, save it, then run calibrate.bat again.
  notepad calibration\videos.txt
  pause
  exit /b 0
)
set PATH=%~dp0.tools;%~dp0.tools\ffmpeg\bin;%PATH%
".venv\Scripts\python.exe" -m scripts.calibrate --file calibration\videos.txt --apply
echo.
echo Restart the server (or sign out and back in for background mode) to use the new settings.
pause
