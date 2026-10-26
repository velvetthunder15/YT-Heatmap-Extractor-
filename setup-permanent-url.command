#!/bin/bash
# Permanent API URL on your own Cloudflare account (free workers.dev, or your domain).
#   bash setup-permanent-url.command            set it up or change it
#   bash setup-permanent-url.command --remove   back to the random quick-tunnel URL
cd "$(dirname "$0")"
bash scripts/setup-tunnel.sh "$@"
