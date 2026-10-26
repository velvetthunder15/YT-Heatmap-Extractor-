#!/bin/bash
# Run the API hidden in the background on macOS, now and at every login.
#   bash install-background.command [--uninstall | --status]
cd "$(dirname "$0")"
bash scripts/background-mac.sh "$@"
