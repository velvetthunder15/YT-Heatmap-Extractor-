# Saves a Cloudflare named-tunnel token and its public hostname into .env, so
# start-windows.bat serves the API at a permanent https URL. See README "Permanent URL".
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
  Write-Host "No .env yet. Run start-windows.bat once first, close it, then run this again." -ForegroundColor Yellow
  exit 1
}

function Set-EnvValue($text, $name, $value) {
  $line = "$name=$value"
  if ($text -match "(?m)^$name=.*$") { return [regex]::Replace($text, "(?m)^$name=.*$", [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line }) }
  return $text.TrimEnd("`r", "`n") + "`r`n" + $line + "`r`n"
}

$text = Get-Content $envFile -Raw
if ($Remove) {
  $text = Set-EnvValue $text "CLOUDFLARE_TUNNEL_TOKEN" ""
  $text = Set-EnvValue $text "PUBLIC_BASE_URL" ""
  Set-Content -Path $envFile -Value $text -NoNewline -Encoding UTF8
  Write-Host "Removed. start-windows.bat will use a free random trycloudflare.com URL again." -ForegroundColor Green
  exit 0
}

Write-Host ""
Write-Host "Permanent URL setup (your own Cloudflare account)" -ForegroundColor Cyan
Write-Host "1. In Cloudflare: Zero Trust > Networks > Tunnels > Create a tunnel > Cloudflared."
Write-Host "2. Copy the install command it shows (the long text with 'eyJ...'). Paste it below."
Write-Host "3. Add a public hostname for the tunnel pointing to service  HTTP  127.0.0.1:8000"
Write-Host ""

$raw = Read-Host "Paste the tunnel token or the whole install command"
$m = [regex]::Match($raw, 'eyJ[A-Za-z0-9_\-=]+(\.[A-Za-z0-9_\-=]+)*')
if (-not $m.Success) { Write-Host "That doesn't contain a tunnel token (it starts with eyJ). Nothing changed." -ForegroundColor Red; exit 1 }
$token = $m.Value

$hostName = (Read-Host "Public hostname you set up (e.g. api.yourdomain.com)").Trim()
$hostName = $hostName -replace '^https?://', '' -replace '/.*$', ''
if ($hostName -notmatch '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$') { Write-Host "That doesn't look like a hostname. Nothing changed." -ForegroundColor Red; exit 1 }

$text = Set-EnvValue $text "CLOUDFLARE_TUNNEL_TOKEN" $token
$text = Set-EnvValue $text "PUBLIC_BASE_URL" "https://$hostName"
Set-Content -Path $envFile -Value $text -NoNewline -Encoding UTF8

Write-Host ""
Write-Host "Saved. Your permanent API URL is  https://$hostName" -ForegroundColor Green
Write-Host "Close the server window if it's open, then double-click start-windows.bat."
Write-Host "Paste https://$hostName into the dashboard once; it never changes again."
