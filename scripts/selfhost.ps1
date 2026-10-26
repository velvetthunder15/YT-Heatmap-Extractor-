# One-command self-hosting on Windows (PowerShell): API + worker + Redis + free Cloudflare tunnel.
#   .\scripts\selfhost.ps1            start and print the public URL + an API key
#   .\scripts\selfhost.ps1 stop       stop everything
#   .\scripts\selfhost.ps1 url        print the current public URL
#   .\scripts\selfhost.ps1 key NAME   create another API key
# If scripts are blocked: powershell -ExecutionPolicy Bypass -File .\scripts\selfhost.ps1
param([string]$Cmd = "up", [string]$Name = "user")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$named = (Test-Path .env) -and (Select-String -Path .env -Pattern '^CLOUDFLARE_TUNNEL_TOKEN=.+' -Quiet)
$tunnelFile = if ($named) { "docker-compose.tunnel-named.yml" } else { "docker-compose.tunnel.yml" }
function DC { docker compose -f docker-compose.yml -f $tunnelFile @args }

function Get-PublicUrl {
  if ($named) {
    $line = Select-String -Path .env -Pattern '^PUBLIC_BASE_URL=(.*)' | Select-Object -First 1
    if ($line) { return ($line.Matches[0].Groups[1].Value -replace '\s*#.*$', '') }
    return ""
  }
  $logs = (DC logs tunnel 2>$null) -join "`n"
  $m = [regex]::Matches($logs, 'https://[a-z0-9-]+\.trycloudflare\.com')
  if ($m.Count -gt 0) { return $m[$m.Count - 1].Value }
  return ""
}

switch ($Cmd) {
  { $_ -in "stop", "down" } { DC down; exit 0 }
  "url" { Get-PublicUrl; exit 0 }
  "key" { DC exec -T api python -m scripts.manage_keys create --name $Name; exit 0 }
  "up" { }
  default { Write-Error "unknown command: $Cmd (use: up | stop | url | key NAME)" }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Error "Docker is not installed. Get Docker Desktop: https://docs.docker.com/get-docker/" }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Write-Error "Docker Desktop is not running. Start it and retry." }

if (-not (Test-Path .env)) {
  Write-Host "Creating .env with a fresh random API_KEY_PEPPER..."
  $chars = [char[]]'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $pepper = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
  (Get-Content .env.example) `
    -replace '^API_KEY_PEPPER=.*', "API_KEY_PEPPER=$pepper" `
    -replace '^WEB_CONCURRENCY=.*', 'WEB_CONCURRENCY=1' `
    -replace '^WORKER_CONCURRENCY=.*', 'WORKER_CONCURRENCY=1' `
    -replace '^GLOBAL_MAX_JOBS=.*', 'GLOBAL_MAX_JOBS=2' |
    Set-Content -Encoding ascii .env
}

Write-Host "Building and starting (first run downloads ~1-2 GB, takes a few minutes)..."
DC up -d --build
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose up failed." }

Write-Host -NoNewline "Waiting for the API to be healthy"
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
  DC exec -T api curl -fsS http://localhost:8000/health *> $null
  if ($LASTEXITCODE -eq 0) { $healthy = $true; break }
  Write-Host -NoNewline "."; Start-Sleep 2
}
Write-Host ""
if (-not $healthy) { Write-Error "API did not become healthy. Run: docker compose logs api" }

Write-Host -NoNewline "Waiting for the public tunnel URL"
$url = ""
for ($i = 0; $i -lt 30; $i++) {
  $url = Get-PublicUrl
  if ($url) { break }
  Write-Host -NoNewline "."; Start-Sleep 2
}
Write-Host ""

$key = ""
if (-not (Test-Path secrets\.first_key_created)) {
  $out = DC exec -T api python -m scripts.manage_keys create --name owner
  $key = ($out | Select-Object -Index 1).Trim()
  New-Item -ItemType File secrets\.first_key_created -Force | Out-Null
}

$base = if ($url) { $url } else { "http://localhost:8000" }
Write-Host ""
Write-Host "================ YouTube Heatmap Extractor is live ================"
Write-Host "Local:   http://localhost:8000/docs"
if ($url) { Write-Host "Public:  $url/docs" } else { Write-Host "Tunnel URL not ready yet. Run: .\scripts\selfhost.ps1 url" }
if ($key) { Write-Host "API key: $key   (shown ONCE - save it now)" }
else { Write-Host "API key: already created earlier. New one: .\scripts\selfhost.ps1 key NAME" }
Write-Host ""
Write-Host "Try it:"
Write-Host "  curl.exe -H `"X-API-Key: $(if ($key) { $key } else { 'YOUR_KEY' })`" `"$base/v1/heatmap?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ`""
if (-not $named) { Write-Host "Note: the trycloudflare URL changes whenever the tunnel restarts." }
Write-Host "Stop with: .\scripts\selfhost.ps1 stop"
