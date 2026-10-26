# Hidden background service for Windows (started by run-hidden.vbs at login).
# Keeps scripts\local-windows.ps1 running, restarts it if it stops, logs to logs\,
# and asks Windows not to idle-sleep while it runs (closing the lid still sleeps).
$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["Out-File:Encoding"] = "utf8"   # so >> redirection writes UTF-8 like the rest of the log
Set-Location (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
New-Item -ItemType Directory -Force "logs" | Out-Null
$log = Join-Path $root "logs\server.log"

# Only one copy at a time.
$mutex = New-Object System.Threading.Mutex($false, "Local\YTHeatmapExtractorBackground")
if (-not $mutex.WaitOne(0)) { exit 0 }

# Keep the PC awake (like macOS caffeinate -i): ES_CONTINUOUS | ES_SYSTEM_REQUIRED.
Add-Type -Namespace YHX -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[void][YHX.Power]::SetThreadExecutionState([uint32]"0x80000001")

while ($true) {
  if ((Test-Path $log) -and (Get-Item $log).Length -gt 5MB) { Move-Item $log "$log.old" -Force }
  "==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') starting ====" | Out-File $log -Append -Encoding UTF8
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local-windows.ps1") -Background *>> $log
  "==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') stopped (exit $LASTEXITCODE), restarting in 15s ====" | Out-File $log -Append -Encoding UTF8
  Start-Sleep 15
}
