#!/bin/bash
# macOS/Linux twin of setup-tunnel.ps1. See README "Permanent URL".
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
if [ ! -f .env ] || [ ! -x "$PY" ]; then
  echo "Run start-mac.command once first (it sets things up), stop it, then run this again."; exit 1
fi
setenv() { "$PY" -c "import sys; from scripts.cf_worker import write_env; write_env(dict(a.split('=', 1) for a in sys.argv[1:]))" "$@"; }

if [ "${1:-}" = "--remove" ]; then
  "$PY" -m scripts.cf_worker remove >/dev/null
  setenv CLOUDFLARE_TUNNEL_TOKEN= PUBLIC_BASE_URL=
  echo "Removed. start-mac.command will use a free random trycloudflare.com URL again."; exit 0
fi

echo
printf '\033[36mPermanent URL setup (uses your own Cloudflare account)\033[0m\n'
echo "  1. Free  https://yt-heatmap-api.<you>.workers.dev  (no domain needed)  [recommended]"
echo "  2. Your own domain, e.g. https://api.yourdomain.com  (named tunnel)"
read -r -p "Choose 1 or 2 [1]: " choice; choice="${choice:-1}"

if [ "$choice" = 1 ]; then
  echo
  echo "1. Sign in (or sign up free) at https://dash.cloudflare.com"
  echo "2. Open https://dash.cloudflare.com/profile/api-tokens > Create Token"
  echo "3. Use the template 'Edit Cloudflare Workers' > Continue to summary > Create Token"
  echo "4. Copy the token and paste it below."
  echo
  read -r -s -p "Cloudflare API token (hidden): " token; echo
  [ -n "$token" ] || { echo "No token entered. Nothing changed."; exit 1; }
  setenv CLOUDFLARE_TUNNEL_TOKEN=   # a named tunnel would take priority
  url="$("$PY" -m scripts.cf_worker setup "$token" | tail -n1)" || { echo "Setup failed (see the error above)."; exit 1; }
elif [ "$choice" = 2 ]; then
  echo
  echo "1. Add your domain to Cloudflare (it must show as Active)."
  echo "2. Zero Trust > Networks > Tunnels > Create a tunnel > Cloudflared. Copy the install command ('eyJ...')."
  echo "3. Add a public hostname pointing to service  HTTP  127.0.0.1:8000"
  echo
  read -r -p "Paste the tunnel token or the whole install command: " raw
  token="$(printf '%s' "$raw" | grep -oE 'eyJ[A-Za-z0-9_=.-]+' | head -n1 || true)"
  [ -n "$token" ] || { echo "That doesn't contain a tunnel token (it starts with eyJ). Nothing changed."; exit 1; }
  read -r -p "Public hostname you set up (e.g. api.yourdomain.com): " host
  host="$(printf '%s' "$host" | sed -E 's#^https?://##; s#/.*$##' | tr -d '[:space:]')"
  printf '%s' "$host" | grep -qE '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' || { echo "That doesn't look like a hostname. Nothing changed."; exit 1; }
  "$PY" -m scripts.cf_worker remove >/dev/null
  setenv "CLOUDFLARE_TUNNEL_TOKEN=$token" "PUBLIC_BASE_URL=https://$host"
  url="https://$host"
else
  echo "Please run it again and type 1 or 2."; exit 1
fi

echo
printf '\033[32mSaved. Your permanent API URL is  %s\033[0m\n' "$url"
echo "Stop the server if it's running (Ctrl+C), then start start-mac.command again."
echo "Paste $url into the dashboard once; it never changes again."
