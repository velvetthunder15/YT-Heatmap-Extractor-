#!/bin/bash
# Replace your API key, for example if it leaked. The old key stops working once the server restarts.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Run start-mac.command once first."; exit 1; fi
KEY="$(.venv/bin/python -m scripts.local_setup --rotate-key | tail -n1)" || { echo "Could not rotate the key."; exit 1; }
echo
echo "Your new API key (also saved in secrets/api_key.txt):"
echo "$KEY"
echo
if launchctl list 2>/dev/null | grep -q com.ytheatmap.server; then
  launchctl kickstart -k "gui/$(id -u)/com.ytheatmap.server" && echo "Background server restarted with the new key."
else
  echo "Now restart the server (close start-mac.command and open it again), then paste the new key into the dashboard."
fi
