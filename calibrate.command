#!/bin/bash
# Tune the estimate against YouTube's own "Most replayed" data.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Run start-mac.command once first."; exit 1; fi
mkdir -p calibration
if [ ! -f calibration/videos.txt ]; then
  echo '# Paste YouTube links that HAVE the "Most replayed" graph, one per line. 10 or more works best.' > calibration/videos.txt
  echo "Add some video links to calibration/videos.txt, save it, then run calibrate.command again."
  open -e calibration/videos.txt 2>/dev/null; exit 0
fi
export PATH="$PWD/.tools:$PWD/.tools/bin:$PATH"
.venv/bin/python -m scripts.calibrate --file calibration/videos.txt --apply
if launchctl list 2>/dev/null | grep -q com.ytheatmap.server; then
  launchctl kickstart -k "gui/$(id -u)/com.ytheatmap.server" && echo "Background server restarted with the new settings."
else
  echo "Restart the server to use the new settings."
fi
