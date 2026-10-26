#!/usr/bin/env bash
# One-command self-hosting: API + worker + Redis + free Cloudflare tunnel, on your own machine.
#   ./scripts/selfhost.sh          start (or restart) and print the public URL + an API key
#   ./scripts/selfhost.sh stop     stop everything
#   ./scripts/selfhost.sh url      print the current public URL
#   ./scripts/selfhost.sh key NAME create another API key
set -euo pipefail
cd "$(dirname "$0")/.."

if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.\+' .env 2>/dev/null; then
  TUNNEL_FILE=docker-compose.tunnel-named.yml; NAMED=1
else
  TUNNEL_FILE=docker-compose.tunnel.yml; NAMED=0
fi
DC=(docker compose -f docker-compose.yml -f "$TUNNEL_FILE")

die() { echo "ERROR: $*" >&2; exit 1; }

public_url() {
  if [ "$NAMED" = 1 ]; then
    grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//'
  else
    "${DC[@]}" logs tunnel 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n1
  fi
}

case "${1:-up}" in
  stop|down) "${DC[@]}" down; exit 0 ;;
  url) public_url; exit 0 ;;
  key) "${DC[@]}" exec -T api python -m scripts.manage_keys create --name "${2:-user}"; exit 0 ;;
  up) ;;
  *) die "unknown command: $1 (use: up | stop | url | key NAME)" ;;
esac

command -v docker >/dev/null || die "Docker is not installed. Get Docker Desktop: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop and retry."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (comes with Docker Desktop)."

if [ ! -f .env ]; then
  echo "Creating .env with a fresh random API_KEY_PEPPER..."
  PEPPER=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48)
  sed -e "s|^API_KEY_PEPPER=.*|API_KEY_PEPPER=${PEPPER}|" \
      -e "s|^WEB_CONCURRENCY=.*|WEB_CONCURRENCY=1|" \
      -e "s|^WORKER_CONCURRENCY=.*|WORKER_CONCURRENCY=1|" \
      -e "s|^GLOBAL_MAX_JOBS=.*|GLOBAL_MAX_JOBS=2|" \
      .env.example > .env
fi

echo "Building and starting (first run downloads ~1-2 GB, takes a few minutes)..."
"${DC[@]}" up -d --build

echo -n "Waiting for the API to be healthy"
for _ in $(seq 1 60); do
  if "${DC[@]}" exec -T api curl -fsS http://localhost:8000/health >/dev/null 2>&1; then echo " ok"; break; fi
  echo -n "."; sleep 2
done
"${DC[@]}" exec -T api curl -fsS http://localhost:8000/health >/dev/null 2>&1 || die "API did not become healthy. Run: docker compose logs api"

echo -n "Waiting for the public tunnel URL"
URL=""
for _ in $(seq 1 30); do
  URL=$(public_url || true)
  [ -n "$URL" ] && break
  echo -n "."; sleep 2
done
echo
[ -n "$URL" ] || echo "Tunnel URL not found yet. Run './scripts/selfhost.sh url' in a minute."

KEY_LINE=""
if [ ! -f secrets/.first_key_created ]; then
  OUT=$("${DC[@]}" exec -T api python -m scripts.manage_keys create --name owner)
  KEY_LINE=$(echo "$OUT" | sed -n 2p)
  touch secrets/.first_key_created
fi

echo
echo "================ YouTube Heatmap Extractor is live ================"
echo "Local:   http://localhost:8000/docs"
[ -n "$URL" ] && echo "Public:  $URL/docs"
if [ -n "$KEY_LINE" ]; then
  echo "API key: $KEY_LINE   (shown ONCE - save it now)"
else
  echo "API key: already created earlier. New one: ./scripts/selfhost.sh key NAME"
fi
echo
echo "Try it:"
echo "  curl -H 'X-API-Key: ${KEY_LINE:-YOUR_KEY}' '${URL:-http://localhost:8000}/v1/heatmap?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ'"
[ "$NAMED" = 0 ] && echo "Note: the trycloudflare URL changes whenever the tunnel restarts."
echo "Stop with: ./scripts/selfhost.sh stop"
