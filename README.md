# YouTube Heatmap Extractor

Paste a YouTube link, get the **most** and **least engaging moments** of the video, with a
dashboard that shows exactly why.

- Uses YouTube's own **"Most replayed"** data when the video has it.
- Otherwise builds a clearly labelled **estimate** from four signals: comments, captions, audio and visuals.
- Never makes numbers up: if nothing usable exists, you get a clear error.

**Dashboard:** https://yt-heatmap-dashboard.netlify.app

| Source | When | Confidence |
|---|---|---|
| `official` | YouTube publishes "Most replayed" data | `high` |
| `estimated` | No official data, so comments, captions, audio and visuals are scored | `high` / `medium` / `low` |
| error | Nothing usable | `no_data_available` (never fabricated) |

---

## Quick start (Windows, about 5 minutes)

You need Windows 10 or 11 and nothing else. No Docker, no WSL, no Redis, no paid hosting.

### 1. Get the code

Either clone it:

```bat
git clone https://github.com/velvetthunder15/YT-Heatmap-Extractor-.git
cd YT-Heatmap-Extractor-
```

or click **Code → Download ZIP** on GitHub and extract it anywhere (for example `Documents\YT-Heatmap-Extractor`).

### 2. Start the server

Double-click **`start-windows.bat`**.

The first run takes a few minutes. It sets everything up inside the project folder:

| Step | What happens |
|---|---|
| Python | Uses Python 3.10 to 3.12 if you have it, otherwise installs 3.11 with `winget` (one time) |
| `.venv\` | A private Python environment with the dependencies |
| `.tools\` | Portable `ffmpeg`, `deno` and `cloudflared` (nothing installed system-wide) |
| `.env` | Settings file, created once (local mode, `REDIS_URL=memory://`, `CORS_ORIGINS=*`) |
| `secrets\api_key.txt` | Your **permanent** API key, created once and reused every start |
| Tunnel | A free Cloudflare quick tunnel that gives your laptop a public `https://` URL |

Later starts take a few seconds.

### 3. Copy your URL and key

When it's ready, the window prints something like:

```
================ YouTube Heatmap Extractor ================
Local docs:  http://127.0.0.1:8000/docs
Public docs: https://random-words-here.trycloudflare.com/docs
API key:     yhx_xxxxxxxxxxxxxxxx   (also saved in secrets\api_key.txt)
```

- **API URL**: the `https://….trycloudflare.com` part (without `/docs`). It **changes every time you restart**.
- **API key**: stays the same forever (it's in `secrets\api_key.txt`).

**Keep this window open.** Closing it or pressing Ctrl+C stops the server.

### 4. Open the dashboard

1. Go to **https://yt-heatmap-dashboard.netlify.app**
2. Tap **Connection**, paste the **API URL** and **API key**, then tap **Test connection**. You should see a green *Connected*.
3. Leave **Remember on this device** ticked so you only paste the key once. After a restart you only update the URL.

### 5. Analyze a video

1. Paste any YouTube link (`watch?v=`, `youtu.be/`, `shorts/` all work) and tap **Analyze**.
2. Official data comes back instantly. An estimate takes a few minutes; the progress bar shows each stage (comments → captions → audio → visuals → scoring).
3. Results are cached, so opening the same video again is instant. Your last 5 videos are under **Recent**.

Want to see it first? Tap **View a sample result** on the dashboard.

### Updating

Re-download the ZIP and extract it over the folder (or `git pull`), then run `start-windows.bat` again.
Your `.env` and API key are kept.

### Is the public URL on my Cloudflare account?

No. It's a Cloudflare **quick tunnel**: anonymous, free, no account or login. `cloudflared` runs on
your laptop and Cloudflare hands out a random `trycloudflare.com` address that forwards to it. Nothing
is created in any Cloudflare account, and the URL stops working as soon as you close the window. For
a URL that never changes, see *Stable URL* under Advanced.

---

## The dashboard

| Panel | What it shows |
|---|---|
| **Overview** | Thumbnail, title, *Official* or *Estimated* badge, confidence and why, length, disclaimer |
| **Key numbers** | Peak moment, biggest drop-off, average engagement, % of hot segments (score ≥ 0.6), signals used. Tap a time to play it |
| **Engagement over time** | Heat strip plus the score curve. Green bands are peaks (numbered), red bands are drop-offs, the dashed line is the average. Hover for each signal's value, click to play from there |
| **Player** | Embedded YouTube player that jumps to any moment you tap |
| **Top moments / Least engaging** | Ranked ranges with score and the signals that drove them, plus a *YouTube ↗* link at that timestamp |
| **Engagement by part of the video** | Average score for each fifth: Intro, Early, Middle, Late, Ending |
| **Signals over time** | Each signal's own curve. Tap the chips to show or hide signals |
| **Signal weights** | How much each signal counts, and any signal that was skipped with the reason |
| **What drove the score** | Each signal's share of the total weighted score |
| **Agreement with final score** | Correlation (−1 to 1) between each signal and the combined score |
| **Score distribution** | How many segments fall in each 0.1 score band |
| **Data** | Download JSON or CSV, copy JSON, view the raw response |
| **About** | Plain-English version of the section below |

The dashboard is a static site in `dashboard/` (plain HTML, CSS and JS, no build step). Your URL and key
are saved only in your browser's local storage and sent only to your own API.

---

## Understanding the results

### Segments

Every video is cut into equal **segments**, 10 seconds by default (5 to 60 s, set with the
dashboard's *Segment size* or the `window` parameter). Everything is scored per segment.

### Score

A number from **0 to 1** for each segment, **relative to the rest of the same video**: 1.00 is
this video's most engaging moment and 0.00 its least. It's a ranking within one video, not a grade,
so 0.8 on one video doesn't mean the same as 0.8 on another.

- **Official** scores are YouTube's relative replay intensity. They are **not** view counts.
- **Estimated** scores are a heuristic, not viewing data. Every estimated response has `"is_estimate": true` and a `disclaimer`.

### Signals

A **signal** is one independent measurement taken for every segment. Each one is min-max scaled to
0–1 within the video (strongest segment = 1, weakest = 0) so they can be blended fairly.

| Signal | Weight | How it's measured |
|---|---|---|
| **Comments** | 0.35 | Finds timestamps people write in comments (`3:42`, `1:02:10`). Each mention is spread over ±5 s, and liked comments count more (weight `1 + ln(1 + likes)`). Up to 2,000 comments. Skipped if fewer than 10 timestamped comments. Uses the YouTube Data API when `YT_API_KEY` is set, else yt-dlp scraping |
| **Captions** (`transcript`) | 0.25 | Transcript text per segment, scored on hook phrases ("watch this", "here's why"), emphasis words ("insane", "biggest"), questions, numbers and claims, topic shifts versus the previous segment, and speech density. Optional LLM rating blended in when `LLM_API_KEY` is set |
| **Audio** | 0.25 | 16 kHz mono audio: `0.5 × loudness (RMS dB) + 0.3 × onset rate (how busy) + 0.2 × bursts`, where bursts are loud and noise-like frames, a cheap detector for laughter, applause and cheering. Past the end of the audio counts as silence |
| **Visuals** | 0.15 | A ≤360p video-only stream decoded by ffmpeg to 64×36 grayscale frames at 2 fps (AV1, VP9 and H.264 all work): `0.6 × cut density + 0.4 × motion`. A cut is a frame jump far above the video's usual change (median + 6 × MAD, at least 25) |

### How the final score is calculated

1. **Split** the video into segments.
2. **Measure** each signal for every segment.
3. **Scale** each signal to 0–1 within the video.
4. **Blend**: `0.35 × comments + 0.25 × captions + 0.25 × audio + 0.15 × visuals`.
5. **Rescale** the blend to 0–1 again, so the top segment is always 1.00.

If a signal can't be measured (comments off, no captions, a download fails), it's dropped and the
remaining weights are scaled up to add to 1. It's listed in `signals_skipped` with the reason, for example
`{"visual": "DownloadError: ..."}`, and the dashboard shows it under *Signal weights*.

### Peaks and drop-offs

The highest-scoring segments seed **top moments** and the lowest seed **drop-offs**. Each seed grows over
neighbouring segments within 0.05 of its score (`MERGE_TOLERANCE`) into one range, and peaks never overlap
drop-offs. For a peak, `signals` lists the signals that contributed at least 20% of its weighted score, with
their `share`.

### Confidence

| Level | Rule (estimated) |
|---|---|
| **high** | Comments with ≥ 50 timestamped comments **plus** ≥ 2 other signals |
| **medium** | Comments plus 1 other signal, **or** captions plus 2 others |
| **low** | Anything thinner |

Official data is always `high`. Estimates are best on videos with lots of timestamped comments and captions.
They find moments that look and sound engaging; they can't see real watch time.

---

## Using the API directly

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
  "signals_skipped": {"visual": "DownloadError: ..."},
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

Common dashboard messages:

| Message | Fix |
|---|---|
| *Couldn't reach the API* | The tunnel URL changed (restart) or the server window was closed. Paste the new URL. If you're on an old version, update so CORS is on |
| *Error 401* | Wrong key. Copy it again from `secrets\api_key.txt` |
| *Error 530 / 502* | The tunnel can't reach your server. Restart `start-windows.bat` |
| `upstream_blocked` | YouTube is blocking the request. See *Reliability* below |

---

## Advanced

### How local mode works

`start-windows.bat` runs `scripts/local-windows.ps1`, which runs `python -m app.local`: uvicorn and an RQ
`SimpleWorker` in one process on an in-memory `fakeredis` (`REDIS_URL=memory://`). Cache and job history
reset when you close the window; the API key stays because only its HMAC hash is stored in `API_KEY_HASHES`
in `.env`. Requests leave from your own internet connection, so YouTube rarely blocks them.

### Stable URL (optional, free)

The quick-tunnel URL changes on every restart. For a fixed one you need your own free Cloudflare account
and a domain on it: create a tunnel in Zero Trust → Networks → Tunnels, then put
`CLOUDFLARE_TUNNEL_TOKEN=...` and `PUBLIC_BASE_URL=https://your.host` in `.env` (Docker path below).

### Free self-hosting with Docker (your own computer + Cloudflare Tunnel)

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

**Stable URL with Docker:** the quick-tunnel URL changes on every restart. For a fixed
one, add a domain to a free Cloudflare account, create a tunnel in Zero Trust → Networks → Tunnels
pointing to `http://api:8000`, then put `CLOUDFLARE_TUNNEL_TOKEN=...` and
`PUBLIC_BASE_URL=https://your.host` in `.env`. The script switches to the named tunnel automatically.

### Paid / cloud deployment

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
  (librosa).

Then create keys with `scripts.manage_keys` inside the API container.

### Reliability: YouTube blocking

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

### API keys

- Keys look like `yhx_...` and are stored only as `HMAC-SHA256(API_KEY_PEPPER, key)`.
- `python -m scripts.manage_keys create --name NAME [--rate N] [--quota N]`, `list`, `revoke HASH`.
- Static keys without Redis records: `python -m scripts.manage_keys hash yhx_...` and put the
  hash in `API_KEY_HASHES`.
- Rate limit is per minute; daily quota resets 00:00 UTC. Polling `/v1/jobs/{id}` counts toward
  the rate limit but not the daily quota.

### Multi-user safety

- Strict URL validation: YouTube hosts only; only the 11-char ID is used downstream (SSRF-safe).
- Cache by video ID: official 24 h, estimated 7 days. One analysis serves any `top`/`bottom`.
- Estimated mode limited to `MAX_ESTIMATE_DURATION` (60 min). Concurrency: `WORKER_CONCURRENCY`
  processes per worker container, plus a cluster-wide `GLOBAL_MAX_JOBS` Redis semaphore.
- Temp audio/video lives in a per-job directory that is deleted in a `finally` block (and the
  temp root is wiped when a worker starts).
- Identical in-flight requests join the same job instead of re-processing.
- Structured JSON logs; no request bodies or keys are logged; nothing is stored beyond the cache
  and job results (which expire).

### Tests

No network, ffmpeg or audio libraries needed:

```bash
pip install -r requirements-dev.txt
pytest -q
```

### Project layout

```
app/
  main.py         FastAPI routes, CORS, error handlers, auth dependency
  local.py        single-process local mode (uvicorn + RQ SimpleWorker on fakeredis)
  config.py       all settings (env vars)
  urls.py         strict YouTube URL parsing
  auth.py         hashed API keys, rate limits, quotas
  cache.py        Redis connection + heatmap cache
  jobs.py         RQ jobs, progress, global semaphore, webhooks
  pipeline.py     fallback chain, confidence, signals_skipped, response rendering
  scoring.py      windows, normalisation, weighting, peak/drop-off merging
  ytdl.py         yt-dlp options, per-download temp folders, proxy/cookies, retry/backoff
  worker.py       multi-process RQ worker entrypoint (Docker mode)
  sources/        official.py comments.py transcript.py audio.py visual.py
dashboard/        static web dashboard (index.html, styles.css, app.js, sample.json)
scripts/
  local-windows.ps1  Windows runner behind start-windows.bat
  local_setup.py     creates .env, CORS and the permanent API key
  manage_keys.py     create / list / revoke keys (Docker mode)
  selfhost.sh/.ps1   Docker + tunnel self-hosting
start-windows.bat
netlify.toml      deploys dashboard/ to Netlify
tests/
```

## Terms of Service

This project scrapes YouTube pages and media outside the official Data API. That can
conflict with [YouTube's Terms of Service](https://www.youtube.com/t/terms). **Review them
(and get legal advice) before running this publicly or as a paid service.** Prefer the
official API where it covers your needs, cache aggressively, and respect rate limits.
