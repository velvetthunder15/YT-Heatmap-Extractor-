# Native Windows runner: no Docker, no WSL, no Redis.
# Sets up a Python venv, downloads portable ffmpeg / Deno / cloudflared into .tools\,
# creates .env + a permanent API key, opens a free Cloudflare tunnel and starts the API.
# Run via start-windows.bat (double-click) or:
#   powershell -ExecutionPolicy Bypass -File .\scripts\local-windows.ps1
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster
Set-Location (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
$tools = Join-Path $root ".tools"
New-Item -ItemType Directory -Force $tools, "secrets", "tmp" | Out-Null

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# ---------- 1. Python 3.10+ ----------
function Find-Python {
  foreach ($c in @(@("py", "-3.11"), @("py", "-3.12"), @("py", "-3.10"), @("python"))) {
    try {
      $exe = $c[0]; $args_ = @($c | Select-Object -Skip 1)
      $v = & $exe @args_ -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
      if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(1[0-3])$') { return ,$c }
    } catch { }
  }
  return $null
}
$py = Find-Python
if (-not $py) {
  Step "Python 3.11 not found - installing it with winget (one time)"
  winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  $py = Find-Python
  if (-not $py) { throw "Python install finished but it is not on PATH yet. Close this window and double-click start-windows.bat again." }
}

# ---------- 2. venv + packages ----------
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Step "Creating Python environment"
  & $py[0] @($py | Select-Object -Skip 1) -m venv .venv
}
$reqHash = (Get-FileHash requirements.txt).Hash
$stamp = Join-Path $root ".venv\.req-hash"
if (-not (Test-Path $stamp) -or (Get-Content $stamp) -ne $reqHash) {
  Step "Installing Python packages (first run: a few minutes)"
  & $venvPy -m pip install --upgrade pip -q
  & $venvPy -m pip install -r requirements.txt -q
  if ($LASTEXITCODE -ne 0) { throw "pip install failed (see messages above)." }
  Set-Content $stamp $reqHash
}

# ---------- 3. Portable tools (no installers) ----------
function Get-Zip($url, $name) {
  $zip = Join-Path $tools "$name.zip"
  Invoke-WebRequest $url -OutFile $zip
  $dest = Join-Path $tools "$name-x"
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Expand-Archive $zip -DestinationPath $dest -Force
  Remove-Item $zip
  return $dest
}
if (-not (Test-Path "$tools\cloudflared.exe")) {
  Step "Downloading cloudflared"
  Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$tools\cloudflared.exe"
}
if (-not (Test-Path "$tools\deno.exe")) {
  Step "Downloading Deno (yt-dlp uses it for YouTube's JS challenges)"
  $d = Get-Zip "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" "deno"
  Move-Item (Get-ChildItem $d -Recurse -Filter deno.exe | Select-Object -First 1).FullName "$tools\deno.exe"
  Remove-Item -Recurse -Force $d
}
if (-not (Test-Path "$tools\ffmpeg.exe")) {
  Step "Downloading ffmpeg (~100 MB, one time)"
  $d = Get-Zip "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "ffmpeg"
  foreach ($exe in "ffmpeg.exe", "ffprobe.exe") {
    Move-Item (Get-ChildItem $d -Recurse -Filter $exe | Select-Object -First 1).FullName "$tools\$exe"
  }
  Remove-Item -Recurse -Force $d
}
$env:Path = "$tools;$env:Path"

# ---------- 4. .env + API key ----------
Step "Preparing config and API key"
$key = (& $venvPy -m scripts.local_setup | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $key) { throw "Config setup failed." }

# ---------- 5. Tunnel + API ----------
$port = 8000
# Clean up leftovers from a previous run whose window was closed with X
# (that skips the cleanup below, so cloudflared / the API can linger in the background).
Get-Process cloudflared -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq "$tools\cloudflared.exe" } | Stop-Process -Force -ErrorAction SilentlyContinue
$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
foreach ($c in $listeners) {
  $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
  if (-not $p) { continue }
  if ($p.Path -like "$root\.venv\*") { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
  else { throw "Port $port is already used by another program ($($p.ProcessName)). Close it and retry." }
}
Start-Sleep -Milliseconds 500
Get-ChildItem $tools -Filter "tunnel-*.log*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
$log = Join-Path $tools ("tunnel-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
# Permanent URL: when setup-permanent-url.bat has put a tunnel token in .env, run that named
# tunnel (your own Cloudflare account + domain). Otherwise open a free quick tunnel (random URL).
function Get-EnvValue($name) {
  $line = Select-String -Path (Join-Path $root ".env") -Pattern "^$name=(.*)$" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $line) { return "" }
  return (($line.Matches[0].Groups[1].Value -split '\s+#')[0]).Trim().Trim('"')
}
$tunnelToken = Get-EnvValue "CLOUDFLARE_TUNNEL_TOKEN"
$publicUrl = (Get-EnvValue "PUBLIC_BASE_URL").TrimEnd("/")
$named = [bool]$tunnelToken
$url = ""
if ($named) {
  Step "Connecting your permanent Cloudflare tunnel"
  $tunnel = Start-Process -FilePath "$tools\cloudflared.exe" `
    -ArgumentList "tunnel", "--no-autoupdate", "run", "--token", $tunnelToken `
    -RedirectStandardError $log -RedirectStandardOutput "$log.out" -WindowStyle Hidden -PassThru
  $ok = $false
  for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    Start-Sleep 1
    if ($tunnel.HasExited) { break }
    if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'Registered tunnel connection' -Quiet)) { $ok = $true }
  }
  if ($ok) { $url = $publicUrl }
  elseif ($tunnel.HasExited) { Write-Host "The tunnel token was rejected. Run setup-permanent-url.bat again with a fresh token." -ForegroundColor Red }
} else {
  Step "Opening free Cloudflare quick tunnel"
  $tunnel = Start-Process -FilePath "$tools\cloudflared.exe" `
    -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$port" `
    -RedirectStandardError $log -RedirectStandardOutput "$log.out" -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep 1
    if (Test-Path $log) {
      $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
      if ($m) { $url = $m.Matches[0].Value }
    }
  }
  # Free permanent URL: point the user's workers.dev Worker at this run's quick tunnel.
  if ($url -and (Get-EnvValue "CF_KV_NAMESPACE_ID")) {
    Step "Pointing your permanent workers.dev URL at this run"
    $w = (& $venvPy -m scripts.cf_worker set-target $url | Select-Object -Last 1)
    if ($LASTEXITCODE -eq 0 -and $w) { $url = $w.Trim(); $named = $true }
    else { Write-Host "Couldn't update the workers.dev URL (see the error above). Using the random URL for now." -ForegroundColor Yellow }
  }
}

Write-Host ""
Write-Host "================ YouTube Heatmap Extractor ================" -ForegroundColor Green
Write-Host "Local docs:  http://127.0.0.1:$port/docs"
if ($url) { Write-Host "Public docs: $url/docs" -ForegroundColor Green; Write-Host "API URL:     $url   (paste this into the dashboard)" -ForegroundColor Green }
else { Write-Host "Public URL not ready (check the tunnel-*.log file in .tools). Local still works." -ForegroundColor Yellow }
Write-Host "API key:     $key   (also saved in secrets\api_key.txt)"
$base = if ($url) { $url } else { "http://127.0.0.1:$port" }
Write-Host ""
Write-Host "Try it in another terminal:"
Write-Host "  curl.exe -H `"X-API-Key: $key`" `"$base/v1/heatmap?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ`""
Write-Host ""
if ($named) { Write-Host "Keep this window open. Close it or press Ctrl+C to stop. Your URL is permanent." -ForegroundColor Yellow }
else { Write-Host "Keep this window open. Close it or press Ctrl+C to stop. This URL changes each start: run setup-permanent-url.bat for a fixed one." -ForegroundColor Yellow }
Write-Host ""

try {
  $env:PORT = "$port"
  & $venvPy -m app.local
} finally {
  if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
}
