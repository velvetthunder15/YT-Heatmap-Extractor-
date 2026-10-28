# install-background.bat / uninstall-background.bat
#   install    run the server hidden now and at every login (no window to keep open)
#   uninstall  stop it and remove it from login
#   status     show whether it's running and its URL
param([ValidateSet("install", "uninstall", "status")][string]$Action = "status")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "YT Heatmap Extractor.lnk"
$statusFile = Join-Path $root "logs\status.txt"

function Get-Service-Procs {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -eq "powershell.exe" -and ($_.CommandLine -like "*background-windows.ps1*" -or ($_.CommandLine -like "*local-windows.ps1*" -and $_.CommandLine -like "*-Background*"))) -or
    ($_.ExecutablePath -like "$root\.venv\*") -or ($_.ExecutablePath -eq "$root\.tools\cloudflared.exe")
  }
}
function Stop-Service-Procs {
  # Parents first so nothing restarts what we kill.
  foreach ($pat in "*background-windows.ps1*", "*local-windows.ps1*") {
    Get-Service-Procs | Where-Object { $_.CommandLine -like $pat } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  }
  Get-Service-Procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

switch ($Action) {
  "install" {
    if (-not (Test-Path ".venv\Scripts\python.exe") -or -not (Test-Path "secrets\api_key.txt")) {
      Write-Host "Run start-windows.bat once first (it sets everything up), close it, then run this again." -ForegroundColor Yellow; exit 1
    }
    # Stop a foreground copy if one is open, so the background one can take port 8000.
    Stop-Service-Procs
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($shortcut)
    $lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"
    $lnk.Arguments = "`"$root\scripts\run-hidden.vbs`""
    $lnk.WorkingDirectory = $root
    $lnk.Description = "Heatmapify API (background)"
    $lnk.Save()
    Remove-Item $statusFile -ErrorAction SilentlyContinue
    Start-Process "$env:WINDIR\System32\wscript.exe" -ArgumentList "`"$root\scripts\run-hidden.vbs`""
    Write-Host "Installed. Starting in the background..." -ForegroundColor Cyan
    for ($i = 0; $i -lt 90 -and -not (Test-Path $statusFile); $i++) { Start-Sleep 1 }
    Write-Host ""
    if (Test-Path $statusFile) { Get-Content $statusFile | Write-Host -ForegroundColor Green }
    else { Write-Host "Still starting. Check logs\server.log, or run background-status.bat in a minute." -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "No window needed: it runs hidden now and starts by itself every time you log in."
    Write-Host "It keeps the PC from idle-sleeping while it runs, but closing the lid or shutting down stops it."
    Write-Host "To stop it for good: uninstall-background.bat"
  }
  "uninstall" {
    Remove-Item $shortcut -ErrorAction SilentlyContinue
    Stop-Service-Procs
    Remove-Item $statusFile -ErrorAction SilentlyContinue
    Write-Host "Stopped and removed from login. Use start-windows.bat to run it in a window again." -ForegroundColor Green
  }
  "status" {
    $running = Get-Service-Procs | Where-Object { $_.CommandLine -like "*background-windows.ps1*" }
    $installed = Test-Path $shortcut
    Write-Host ("Installed at login: " + $(if ($installed) { "yes" } else { "no" }))
    Write-Host ("Running now:        " + $(if ($running) { "yes" } else { "no" }))
    if ($running -and (Test-Path $statusFile)) { Write-Host ""; Get-Content $statusFile | Write-Host -ForegroundColor Green }
    Write-Host ""; Write-Host "Log: $root\logs\server.log"
  }
}
