#!/bin/bash
# macOS background service (launchd LaunchAgent): no Terminal window to keep open.
#   bash install-background.command               install + start now, and at every login
#   bash install-background.command --uninstall   stop and remove
#   bash install-background.command --status      is it running? what's the URL?
# launchd restarts it if it stops; caffeinate keeps the Mac from idle-sleeping while it runs.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.ytheatmap.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
STATUS="$ROOT/logs/status.txt"
mkdir -p logs "$HOME/Library/LaunchAgents"

case "${1:-}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST" "$STATUS"
    pkill -f "$ROOT/.tools/cloudflared" 2>/dev/null || true
    pkill -f "$ROOT/.venv/bin/python -m app.local" 2>/dev/null || true
    echo "Stopped and removed from login. Use start-mac.command to run it in a window again."
    exit 0 ;;
  --status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo "Running in background: yes"; [ -f "$STATUS" ] && { echo; cat "$STATUS"; }
    else echo "Running in background: no"; fi
    echo; echo "Log: $ROOT/logs/server.log"
    exit 0 ;;
  ""|--install) ;;
  *) sed -n '2,6p' "$0"; exit 1 ;;
esac

if [ ! -x .venv/bin/python ] || [ ! -f secrets/api_key.txt ]; then
  echo "Run  bash start-mac.command  once first (it sets everything up), stop it with Ctrl+C, then run this again."; exit 1
fi
# macOS privacy rules block background jobs from reading Desktop, Documents and Downloads.
case "$ROOT" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "This folder is in Desktop, Documents or Downloads, which macOS won't let background jobs read."
    echo "Move it to your home folder first, for example:"
    echo "  mv \"$ROOT\" ~/YT-Heatmap-Extractor && cd ~/YT-Heatmap-Extractor && bash install-background.command"
    exit 1 ;;
esac

# Stop a foreground copy if one is open, so the background one can take port 8000.
pkill -f "$ROOT/.tools/cloudflared" 2>/dev/null || true
pkill -f "$ROOT/.venv/bin/python -m app.local" 2>/dev/null || true
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
rm -f "$STATUS"

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>/bin/bash</string><string>$ROOT/scripts/local-mac.sh</string><string>--background</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$ROOT/logs/server.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/server.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
</dict>
</plist>
PL
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed. Starting in the background..."
for _ in $(seq 90); do [ -f "$STATUS" ] && break; sleep 1; done
echo
if [ -f "$STATUS" ]; then cat "$STATUS"; else echo "Still starting. Check logs/server.log, or run: bash install-background.command --status"; fi
echo
echo "No window needed: it runs hidden now and starts by itself every time you log in."
echo "It keeps the Mac from idle-sleeping while it runs, but closing the lid or shutting down stops it."
echo "To stop it for good: bash install-background.command --uninstall"
