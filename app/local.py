"""Single-process local mode: API + job worker in one Python process, no Redis, no Docker.

Use with REDIS_URL=memory:// (in-memory store; cache and jobs reset on restart).
    python -m app.local
Works on Windows, macOS and Linux. Started by start-windows.bat / scripts/local-windows.ps1.
"""
from __future__ import annotations

import os
import shutil
import signal
import threading
import time

from .config import get_settings
from .logging_setup import setup_logging


def _serve_api(host: str, port: int) -> None:
    import uvicorn

    # proxy_headers + forwarded_allow_ips: behind cloudflared, links come out as https.
    uvicorn.run("app.main:app", host=host, port=port, proxy_headers=True,
                forwarded_allow_ips="*", log_level="warning")


def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    shutil.rmtree(s.tmp_dir, ignore_errors=True)
    os.makedirs(s.tmp_dir, exist_ok=True)

    from rq import SimpleWorker

    from .cache import get_redis
    from .jobs import QUEUE_NAME

    port = int(os.environ.get("PORT", "8000"))
    t = threading.Thread(target=_serve_api, args=("127.0.0.1", port), daemon=True, name="api")
    t.start()
    time.sleep(1.0)
    print(f"API running on http://127.0.0.1:{port}  (Ctrl+C to stop)", flush=True)

    worker = SimpleWorker([QUEUE_NAME], connection=get_redis())
    if not hasattr(signal, "SIGALRM"):  # Windows: no SIGALRM, use a timer-based job timeout
        from rq.timeouts import TimerDeathPenalty

        worker.death_penalty_class = TimerDeathPenalty
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
