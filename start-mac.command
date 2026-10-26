#!/bin/bash
# Double-click (or run `bash start-mac.command` in Terminal) to run the
# YouTube Heatmap Extractor on macOS. No Docker, no admin rights.
cd "$(dirname "$0")"
bash scripts/local-mac.sh "$@"
