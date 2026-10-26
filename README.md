# YouTube Heatmap Extractor

A hosted REST API that takes a YouTube URL and returns the **most** and **least engaging**
segments of the video, for every video, including ones too new or too small to have
YouTube's "Most replayed" graph.

| Source | When | Confidence |
|---|---|---|
| `official` | YouTube publishes "Most replayed" data | `high` |
| `estimated` | No official data: comments, captions, audio and visuals are scored | `high` / `medium` / `low` |
| error | Nothing usable | `no_data_available` (never fabricated) |

> **Read this first.** Official scores are YouTube's *relative replay intensity* (0-1, the
> busiest moment is 1.0). They are **not** view counts. Estimated scores are a **heuristic**,
> not viewing data; they are most reliable on videos with many timestamped comments and
> captions. Every estimated response carries `"is_estimate": true` and a `disclaimer`.

---

## Quick start (local)

```bash
cp .env.example .env               # set API_KEY_PEPPER to a long random string
docker compose up -d --build       # api on :8000, worker, redis
docker compose exec api python -m scripts.manage_keys create --name me --rate 60 --quota 1000
# -> prints yhx_... (shown once)
open http://localhost:8000/docs    # interactive OpenAPI docs
```

Run the tests (no network, no ffmpeg needed):

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Usage

```bash
export KEY=yhx_your_key
export API=http://localhost:8000
```

**Fast path:** official or cached data comes back immediately with `200`.

```bash
curl -s -H "X-API-Key: $KEY" \
  "$API/v1/heatmap?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ&top=5&bottom=5"
```

If the video has no official heatmap, the same call queues an estimate and returns `202`:

```json
{"job_id": "5f0c...", "status": "queued", "status_url": "http://localhost:8000/v1/jobs/5f0c...",
 "message": "No official heatmap is available; an estimate is being computed."}
```

**Slow path:** queue explicitly (optionally with a webhook):

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/VIDEO_ID","top":5,"bottom":5,"window":10,
       "force_estimate":false,"webhook_url":"https://example.com/hooks/heatmap"}' \
  "$API/v1/jobs"

curl -s -H "X-API-Key: $KEY" "$API/v1/jobs/JOB_ID"
# {"job_id":"...","status":"processing","progress":0.55,"stage":"analysing audio","result":null}
```

Statuses: `queued | processing | done | failed`. Jobs are private to the key that created
them. Webhooks receive `{"job_id", "status", "result"}` or `{"job_id", "status", "error"}`.
They must be public `https://` URLs (private/loopback addresses are rejected).

### Response

```json
{
  "video_id": "abc123XYZ_0",
  "title": "...",
  "duration": 612,
  "source": "estimated",
  "is_estimate": true,
  "confidence": "medium",
  "confidence_reason": "3 signals available (comments, transcript, audio), 23 timestamped comments.",
  "signals_used": ["comments", "transcript", "audio"],
  "weights": {"comments": 0.412, "transcript": 0.294, "audio": 0.294},
  "window_seconds": 10,
  "most_engaging": [
    {"start": 220, "end": 250, "start_hms": "00:03:40", "end_hms": "00:04:10", "score": 1.0,
     "type": "peak", "link": "https://youtu.be/abc123XYZ_0?t=220",
     "signals": [{"name": "comments", "value": 0.97, "share": 0.61}, {"name": "audio", "value": 0.8, "share": 0.25}]}
  ],
  "least_engaging": [
    {"start": 480, "end": 510, "start_hms": "00:08:00", "end_hms": "00:08:30", "score": 0.0,
     "type": "drop-off", "link": "https://youtu.be/abc123XYZ_0?t=480",
     "signals": [{"name": "comments", "value": 0.0}, {"name": "audio", "value": 0.05}]}
  ],
  "full_heatmap": [{"start": 0, "end": 10, "score": 0.31, "signals": {"comments": 0.2, "audio": 0.5}}],
  "disclaimer": "Estimated from comments, captions, audio and visuals. This is a heuristic, not real viewer data.",
  "cached": false
}
```

### Errors

Always `{"error": {"code": "...", "message": "..."}}`:

| HTTP | code | meaning |
|---|---|---|
| 400 | `invalid_url` | not a YouTube video URL / ID |
| 401 | `unauthorized` | missing or invalid `X-API-Key` |
| 403 | `video_private`, `video_age_restricted` | can't be analysed (age-restricted works with cookies) |
| 404 | `video_unavailable`, `job_not_found` | removed video, unknown/expired job |
| 422 | `video_live`, `video_too_long`, `no_data_available`, `validation_error` | |
| 429 | `rate_limited`, `quota_exceeded` | per-minute limit / daily quota (has `Retry-After`) |
| 502 | `upstream_blocked` | YouTube blocked this server; configure a proxy or cookies |

## How it works

1. **Official**: yt-dlp metadata (`info["heatmap"]`, ~100 segments). Fallback: `ytInitialData`
   on the watch page (legacy `heatMarkers` and newer `macroMarkersListEntity` formats).
2. **Estimated** (video split into `WINDOW_SECONDS` windows, each signal min-max normalised):
   - **Comments (0.35)**: `3:42` / `1:02:10` mentions, each spread +/-5 s, weighted by likes.
     Skipped below `MIN_TIMESTAMPED_COMMENTS` (10). YouTube Data API when `YT_API_KEY` is set
     (quota tracked in Redis, falls back to yt-dlp scraping when exhausted).
   - **Transcript (0.25)**: topic shifts, questions, emphasis words, hook phrases, numeric
     claims, speech density. Optional LLM pass (`LLM_API_KEY`) blended in.
   - **Audio (0.25)**: RMS loudness, onset rate (speech pace), loud + noisy bursts
     (laughter/applause).
   - **Visual (0.15)**: PySceneDetect cut density + frame-difference motion on a <=360p stream.
   - Unavailable or failing signals are dropped and weights renormalised.
3. Top/bottom N seeds are grown over neighbours within `MERGE_TOLERANCE` (0.05) into ranges;
   peaks and drop-offs never overlap.

Confidence (estimated): **high** = comments with >=50 timestamped comments plus >=2 other
signals; **medium** = comments plus one more, or transcript plus two more; **low** = otherwise.

## API keys

- Keys look like `yhx_...` and are stored only as `HMAC-SHA256(API_KEY_PEPPER, key)`.
- `python -m scripts.manage_keys create --name NAME [--rate N] [--quota N]`, `list`, `revoke HASH`.
- Static keys without Redis records: `python -m scripts.manage_keys hash yhx_...` and put the
  hash in `API_KEY_HASHES`.
- Rate limit is per minute; daily quota resets 00:00 UTC. Polling `/v1/jobs/{id}` counts toward
  the rate limit but not the daily quota.

## Multi-user safety

- Strict URL validation: YouTube hosts only; only the 11-char ID is used downstream (SSRF-safe).
- Cache by video ID: official 24 h, estimated 7 days. One analysis serves any `top`/`bottom`.
- Estimated mode limited to `MAX_ESTIMATE_DURATION` (60 min). Concurrency: `WORKER_CONCURRENCY`
  processes per worker container, plus a cluster-wide `GLOBAL_MAX_JOBS` Redis semaphore.
- Temp audio/video lives in a per-job directory that is deleted in a `finally` block (and the
  temp root is wiped when a worker starts).
- Identical in-flight requests join the same job instead of re-processing.
- Structured JSON logs; no request bodies or keys are logged; nothing is stored beyond the cache
  and job results (which expire).

## Reliability: YouTube blocking

YouTube routinely blocks datacenter IPs ("Sign in to confirm you're not a bot"). You will
almost certainly need one of:

- `YT_PROXY=http://user:pass@host:port`: a **residential** proxy works best.
- `YT_COOKIES_FILE=/secrets/cookies.txt`: Netscape-format cookies from a throwaway account,
  mounted via `./secrets`. This also unlocks age-restricted videos.

All yt-dlp calls retry with exponential backoff and surface `upstream_blocked` instead of
failing silently. The image includes Deno, which current yt-dlp needs to solve YouTube's
player challenges.

**Upgrading yt-dlp** (do this whenever extraction breaks):

```bash
make bump-ytdlp V=2026.11.01
# or without editing requirements: docker compose build --build-arg YTDLP_VERSION=2026.11.01
```

## Windows, no Docker (simplest)

Needs nothing but Windows 10/11. Download or clone the repo, then **double-click
`start-windows.bat`**. The first run installs Python 3.11 via winget if you don't have it, creates
a `.venv`, downloads portable ffmpeg, Deno and cloudflared into `.tools\` (nothing system-wide),
creates `.env` plus a permanent API key (`secrets\api_key.txt`), opens a free Cloudflare quick
tunnel and prints your public `https://<random>.trycloudflare.com` URL.

It runs in **single-process local mode** (`REDIS_URL=memory://`, `python -m app.local`): API and
worker share one process with an in-memory store, so there's no Redis to install. Cache and job
history reset when you close the window; the API key stays. Keep the window open while you want it live.

## Free self-hosting with Docker (your own computer + Cloudflare Tunnel)

Costs nothing, and because requests leave from your home/college internet (not a datacenter IP),
YouTube is far less likely to block extraction, so no proxy is needed. The API is online only
while your computer is on and Docker is running.

1. Install [Docker Desktop](https://docs.docker.com/get-docker/) and start it.
2. `git clone https://github.com/velvetthunder15/YT-Heatmap-Extractor-.git && cd YT-Heatmap-Extractor-`
3. Run one command:
   - macOS / Linux / WSL: `./scripts/selfhost.sh`
   - Windows PowerShell: `powershell -ExecutionPolicy Bypass -File .\scripts\selfhost.ps1`

It creates `.env` (random pepper, laptop-sized concurrency), builds and starts API + worker +
Redis + a Cloudflare quick tunnel, waits for `/health`, and prints your public
`https://<random>.trycloudflare.com` URL plus your first API key (shown once).

Other commands: `selfhost.sh url` (current URL), `selfhost.sh key NAME` (new key),
`selfhost.sh stop`.

**Stable URL (optional, still free):** the quick-tunnel URL changes on every restart. For a fixed
one, add a domain to a free Cloudflare account, create a tunnel in Zero Trust → Networks → Tunnels
pointing to `http://api:8000`, then put `CLOUDFLARE_TUNNEL_TOKEN=...` and
`PUBLIC_BASE_URL=https://your.host` in `.env`. The script switches to the named tunnel automatically.

## Deployment

Needs long-running workers and ffmpeg, so it is **not suited to serverless** (Lambda, Vercel,
Cloud Functions). Use a container host:

- **Render**: a *Web Service* (Dockerfile, default CMD) + a *Background Worker* (same repo,
  start command `python -m app.worker`) + *Render Key Value* (Redis). Set env vars from
  `.env.example`; set `PUBLIC_BASE_URL`.
- **Railway**: deploy the repo twice (api / worker with start command `python -m app.worker`)
  and add the Redis plugin; reference `${{Redis.REDIS_URL}}`.
- **Fly.io**: `fly launch`, then define `[processes] app = "gunicorn ..."`,
  `worker = "python -m app.worker"`, and attach Upstash Redis (`fly redis create`).
- **VPS**: `docker compose up -d` behind Caddy or nginx with TLS. Give the worker 2+ GB RAM
  (librosa + OpenCV).

Then create keys with `scripts.manage_keys` inside the API container.

## Project layout

```
app/
  main.py         FastAPI routes, error handlers, auth dependency
  config.py       all settings (env vars)
  urls.py         strict YouTube URL parsing
  auth.py         hashed API keys, rate limits, quotas
  cache.py        Redis connection + heatmap cache
  jobs.py         RQ jobs, progress, global semaphore, webhooks
  pipeline.py     fallback chain, confidence, response rendering
  scoring.py      windows, normalisation, weighting, peak/drop-off merging
  ytdl.py         yt-dlp options, proxy/cookies, retry/backoff, error mapping
  worker.py       multi-process RQ worker entrypoint
  sources/        official.py comments.py transcript.py audio.py visual.py
scripts/manage_keys.py
tests/            URL parsing, scoring/merging, fallback chain, API (fakeredis)
```

## Terms of Service

This project scrapes YouTube pages and media outside the official Data API. That can
conflict with [YouTube's Terms of Service](https://www.youtube.com/t/terms). **Review them
(and get legal advice) before running this publicly or as a paid service.** Prefer the
official API where it covers your needs, cache aggressively, and respect rate limits.
