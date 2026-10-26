# Gives the API a permanent URL using the user's own Cloudflare account. Two ways:
#   1. Free workers.dev URL (no domain): a small Worker forwards to the quick tunnel,
#      and start-windows.bat updates it on every start. Handled by scripts/cf_worker.py.
#   2. Your own domain: a named Cloudflare Tunnel (token + hostname saved in .env).
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $envFile) -or -not (Test-Path $venvPy)) {
  Write-Host "Run start-windows.bat once first (it sets things up), close it, then run this again." -ForegroundColor Yellow
  exit 1
}
Set-Location $root

function Set-EnvValue($text, $name, $value) {
  $line = "$name=$value"
  if ($text -match "(?m)^$name=.*$") { return [regex]::Replace($text, "(?m)^$name=.*$", [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line }) }
  return $text.TrimEnd("`r", "`n") + "`r`n" + $line + "`r`n"
}
function Clear-Named {
  $t = Get-Content $envFile -Raw
  $t = Set-EnvValue $t "CLOUDFLARE_TUNNEL_TOKEN" ""
  $t = Set-EnvValue $t "PUBLIC_BASE_URL" ""
  Set-Content -Path $envFile -Value $t -NoNewline -Encoding UTF8
}

if ($Remove) {
  & $venvPy -m scripts.cf_worker remove | Out-Null
  Clear-Named
  Write-Host "Removed. start-windows.bat will use a free random trycloudflare.com URL again." -ForegroundColor Green
  exit 0
}

Write-Host ""
Write-Host "Permanent URL setup (uses your own Cloudflare account)" -ForegroundColor Cyan
Write-Host "  1. Free  https://yt-heatmap-api.<you>.workers.dev  (no domain needed)  [recommended]"
Write-Host "  2. Your own domain, e.g. https://api.yourdomain.com  (named tunnel)"
$choice = (Read-Host "Choose 1 or 2 [1]").Trim()
if (-not $choice) { $choice = "1" }

if ($choice -eq "1") {
  Write-Host ""
  Write-Host "1. Sign in (or sign up free) at https://dash.cloudflare.com"
  Write-Host "2. Open https://dash.cloudflare.com/profile/api-tokens > Create Token"
  Write-Host "3. Use the template 'Edit Cloudflare Workers' > Continue to summary > Create Token"
  Write-Host "4. Copy the token and paste it below."
  Write-Host ""
  $token = (Read-Host "Cloudflare API token").Trim()
  if (-not $token) { Write-Host "No token entered. Nothing changed." -ForegroundColor Red; exit 1 }
  Clear-Named   # a named tunnel would take priority, so switch it off
  $url = (& $venvPy -m scripts.cf_worker setup $token | Select-Object -Last 1)
  if ($LASTEXITCODE -ne 0 -or -not $url) { Write-Host "Setup failed (see the error above). Nothing else changed." -ForegroundColor Red; exit 1 }
  $url = $url.Trim()
} elseif ($choice -eq "2") {
  Write-Host ""
  Write-Host "1. Add your domain to Cloudflare (it must show as Active)."
  Write-Host "2. Zero Trust > Networks > Tunnels > Create a tunnel > Cloudflared. Copy the install command ('eyJ...')."
  Write-Host "3. Add a public hostname pointing to service  HTTP  127.0.0.1:8000"
  Write-Host ""
  $raw = Read-Host "Paste the tunnel token or the whole install command"
  $m = [regex]::Match($raw, 'eyJ[A-Za-z0-9_\-=]+(\.[A-Za-z0-9_\-=]+)*')
  if (-not $m.Success) { Write-Host "That doesn't contain a tunnel token (it starts with eyJ). Nothing changed." -ForegroundColor Red; exit 1 }
  $hostName = (Read-Host "Public hostname you set up (e.g. api.yourdomain.com)").Trim()
  $hostName = $hostName -replace '^https?://', '' -replace '/.*$', ''
  if ($hostName -notmatch '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$') { Write-Host "That doesn't look like a hostname. Nothing changed." -ForegroundColor Red; exit 1 }
  & $venvPy -m scripts.cf_worker remove | Out-Null
  $t = Get-Content $envFile -Raw
  $t = Set-EnvValue $t "CLOUDFLARE_TUNNEL_TOKEN" $m.Value
  $t = Set-EnvValue $t "PUBLIC_BASE_URL" "https://$hostName"
  Set-Content -Path $envFile -Value $t -NoNewline -Encoding UTF8
  $url = "https://$hostName"
} else { Write-Host "Please run it again and type 1 or 2." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Saved. Your permanent API URL is  $url" -ForegroundColor Green
Write-Host "Close the server window if it's open, then double-click start-windows.bat."
Write-Host "Paste $url into the dashboard once; it never changes again."
