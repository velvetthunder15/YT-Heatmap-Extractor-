#!/bin/bash
# Native macOS runner: no Docker, no Redis, no admin rights.
# Sets up a Python venv, downloads portable ffmpeg / Deno / cloudflared into .tools/,
# creates .env + a permanent API key, opens a Cloudflare tunnel and starts the API.
# Run via start-mac.command (double-click) or:  bash start-mac.command
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
TOOLS="$ROOT/.tools"
mkdir -p "$TOOLS" secrets tmp logs
BACKGROUND=0; [ "${1:-}" = "--background" ] && BACKGROUND=1
if [ "$BACKGROUND" = 1 ]; then
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') starting ===="
  # keep the launchd log from growing forever
  if [ -f logs/server.log ] && [ "$(wc -c < logs/server.log)" -gt 5000000 ]; then tail -c 1000000 logs/server.log > logs/server.log.tmp && cat logs/server.log.tmp > logs/server.log && rm logs/server.log.tmp; fi
fi
step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*"; exit 1; }

case "$(uname -m)" in
  arm64)  CF_ARCH=arm64; DENO_ARCH=aarch64; FF_ARCH=arm64; UV_ARCH=aarch64 ;;
  x86_64) CF_ARCH=amd64; DENO_ARCH=x86_64;  FF_ARCH=amd64; UV_ARCH=x86_64 ;;
  *) die "Unsupported CPU: $(uname -m)" ;;
esac
fetch() { curl -fsSL --retry 3 "$1" -o "$2"; }

# ---------- 1. Python 3.10-3.13 (macOS's built-in python3 is usually too old) ----------
VENV_PY="$ROOT/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  PY=""
  for c in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -n "$PY" ]; then
    step "Creating Python environment ($($PY --version))"
    "$PY" -m venv .venv
  else
    # No suitable Python: fetch uv (single binary) and let it download Python 3.12 into the venv.
    step "Python 3.10+ not found - downloading a private Python 3.12 (one time, no admin needed)"
    if [ ! -x "$TOOLS/uv" ]; then
      fetch "https://github.com/astral-sh/uv/releases/latest/download/uv-${UV_ARCH}-apple-darwin.tar.gz" "$TOOLS/uv.tgz"
      tar -xzf "$TOOLS/uv.tgz" -C "$TOOLS" && mv "$TOOLS"/uv-*/uv "$TOOLS/uv" && rm -rf "$TOOLS"/uv-* "$TOOLS/uv.tgz"
    fi
    UV_PYTHON_INSTALL_DIR="$TOOLS/python" "$TOOLS/uv" venv --seed --python 3.12 .venv
  fi
fi

# ---------- 2. Packages ----------
REQ_HASH="$(shasum -a 256 requirements.txt | cut -d' ' -f1)"
if [ "$(cat .venv/.req-hash 2>/dev/null || true)" != "$REQ_HASH" ]; then
  step "Installing Python packages (first run: a few minutes)"
  "$VENV_PY" -m pip install --upgrade pip -q
  "$VENV_PY" -m pip install -r requirements.txt -q || die "pip install failed (see messages above)."
  echo "$REQ_HASH" > .venv/.req-hash
fi

# ---------- 3. Portable tools ----------
if [ ! -x "$TOOLS/cloudflared" ]; then
  step "Downloading cloudflared"
  fetch "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-${CF_ARCH}.tgz" "$TOOLS/cf.tgz"
  tar -xzf "$TOOLS/cf.tgz" -C "$TOOLS" && rm "$TOOLS/cf.tgz" && chmod +x "$TOOLS/cloudflared"
fi
if [ ! -x "$TOOLS/deno" ]; then
  step "Downloading Deno (yt-dlp uses it for YouTube's JS challenges)"
  fetch "https://github.com/denoland/deno/releases/latest/download/deno-${DENO_ARCH}-apple-darwin.zip" "$TOOLS/deno.zip"
  unzip -oq "$TOOLS/deno.zip" -d "$TOOLS" && rm "$TOOLS/deno.zip" && chmod +x "$TOOLS/deno"
fi
for bin in ffmpeg ffprobe; do
  if [ ! -x "$TOOLS/$bin" ]; then
    step "Downloading $bin (one time)"
    fetch "https://ffmpeg.martin-riedl.de/redirect/latest/macos/${FF_ARCH}/release/${bin}.zip" "$TOOLS/$bin.zip"
    unzip -oq "$TOOLS/$bin.zip" -d "$TOOLS" && rm "$TOOLS/$bin.zip" && chmod +x "$TOOLS/$bin"
  fi
done
xattr -d com.apple.quarantine "$TOOLS"/* 2>/dev/null || true
export PATH="$TOOLS:$PATH"

# ---------- 4. .env + API key ----------
step "Preparing config and API key"
KEY="$("$VENV_PY" -m scripts.local_setup | tail -n1 | tr -d '[:space:]')"
[ -n "$KEY" ] || die "Config setup failed."
envget() { "$VENV_PY" -c "from scripts.cf_worker import read_env; print(read_env().get('$1', ''))"; }

# ---------- 5. Tunnel + API (with a watchdog that reconnects the tunnel) ----------
PORT=8000
STATUS="$ROOT/logs/status.txt"
LABEL="com.ytheatmap.server"

# If the background service is running, don't start a second copy that would fight it.
if [ "$BACKGROUND" = 0 ] && launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo
  printf '\033[32mThe server is already running in the background (install-background.command).\033[0m\n'
  [ -f "$STATUS" ] && cat "$STATUS"
  warn "Nothing else to do. To stop it: bash install-background.command --uninstall"
  exit 0
fi

pkill -f "$TOOLS/cloudflared" 2>/dev/null || true
for pid in $(lsof -ti tcp:$PORT -sTCP:LISTEN 2>/dev/null || true); do
  if ps -o command= -p "$pid" | grep -q "$ROOT/.venv"; then kill -9 "$pid" 2>/dev/null || true
  else die "Port $PORT is already used by another program ($(ps -o comm= -p "$pid")). Close it and retry."; fi
done
sleep 0.5

TUNNEL_TOKEN="$(envget CLOUDFLARE_TUNNEL_TOKEN)"
PUBLIC_URL="$(envget PUBLIC_BASE_URL)"; PUBLIC_URL="${PUBLIC_URL%/}"
USE_WORKER=0; [ -n "$(envget CF_KV_NAMESPACE_ID)" ] && USE_WORKER=1
TUNNEL_PID=""; APP_PID=""; URL=""; NAMED=0

# Starts cloudflared; sets TUNNEL_PID, URL, NAMED.
start_tunnel() {
  rm -f "$TOOLS"/tunnel-*.log
  local log="$TOOLS/tunnel-$(date +%Y%m%d-%H%M%S).log"
  URL=""; NAMED=0
  if [ -n "$TUNNEL_TOKEN" ]; then
    step "Connecting your permanent Cloudflare tunnel"
    "$TOOLS/cloudflared" tunnel --no-autoupdate run --token "$TUNNEL_TOKEN" >"$log" 2>&1 &
    TUNNEL_PID=$!
    for _ in $(seq 30); do
      sleep 1
      kill -0 "$TUNNEL_PID" 2>/dev/null || { warn "The tunnel token was rejected. Run setup-permanent-url.command again with a fresh token."; return 0; }
      if grep -q "Registered tunnel connection" "$log"; then URL="$PUBLIC_URL"; NAMED=1; return 0; fi
    done
    return 0
  fi
  step "Opening free Cloudflare quick tunnel"
  "$TOOLS/cloudflared" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" >"$log" 2>&1 &
  TUNNEL_PID=$!
  for _ in $(seq 30); do
    sleep 1
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" | head -n1 || true)"
    [ -n "$URL" ] && break
  done
  if [ -n "$URL" ] && [ "$USE_WORKER" = 1 ]; then
    step "Pointing your permanent workers.dev URL at this run"
    local w
    if w="$("$VENV_PY" -m scripts.cf_worker set-target "$URL" | tail -n1)" && [ -n "$w" ]; then URL="$w"; NAMED=1
    else warn "Couldn't update the workers.dev URL (see the error above). Using the random URL for now."; fi
  fi
}

write_status() {
  {
    echo "API URL:  ${URL:-(not ready - local only: http://127.0.0.1:$PORT)}"
    echo "API key:  $KEY"
    echo "Updated:  $(date '+%Y-%m-%d %H:%M:%S')"
  } > "$STATUS"
}

cleanup() {
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

start_tunnel
write_status

echo
printf '\033[32m================ YouTube Heatmap Extractor ================\033[0m\n'
echo "Local docs:  http://127.0.0.1:$PORT/docs"
if [ -n "$URL" ]; then
  printf '\033[32mPublic docs: %s/docs\nAPI URL:     %s   (paste this into the dashboard)\033[0m\n' "$URL" "$URL"
else
  warn "Public URL not ready (check the tunnel-*.log file in .tools). Local still works."
fi
echo "API key:     $KEY   (also saved in secrets/api_key.txt)"
BASE="${URL:-http://127.0.0.1:$PORT}"
echo
echo "Try it in another Terminal window:"
echo "  curl -H \"X-API-Key: $KEY\" \"$BASE/v1/heatmap?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ\""
echo
if [ "$BACKGROUND" = 0 ]; then
  if [ "$NAMED" = 1 ]; then warn "Keep this window open. Close it or press Ctrl+C to stop. Your URL is permanent."
  else warn "Keep this window open. Close it or press Ctrl+C to stop. This URL changes each start: run setup-permanent-url.command for a fixed one."; fi
  warn "Don't want a window at all? Run  bash install-background.command  once: it runs hidden and starts when you log in."
  echo
fi

PORT=$PORT "$VENV_PY" -m app.local &
APP_PID=$!
# Watchdog: if cloudflared dies (network drop it couldn't recover from), start it again.
while kill -0 "$APP_PID" 2>/dev/null; do
  sleep 5
  if [ -n "$TUNNEL_PID" ] && ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    warn "$(date +%H:%M:%S) Tunnel dropped - reconnecting..."
    sleep 5
    start_tunnel
    write_status
    [ -n "$URL" ] && printf '\033[32mReconnected: %s\033[0m\n' "$URL"
  fi
done
wait "$APP_PID" || warn "The API process stopped (exit code $?)."
