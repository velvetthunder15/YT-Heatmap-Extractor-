"""Shared yt-dlp plumbing: options (proxy/cookies), retry with backoff, error mapping.

yt-dlp is imported lazily so the API and the tests start without it loaded.
"""
from __future__ import annotations

import logging
import os
import tempfile
import random
import time
from typing import Any, Callable, TypeVar

from .config import get_settings
from .errors import PERMANENT_ERRORS, APIError, UpstreamBlocked, classify_ytdlp_error
from .logging_setup import log_event

log = logging.getLogger(__name__)
T = TypeVar("T")


class _YDLLogger:
    """Route yt-dlp output into our structured logs instead of stderr."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        log.debug("yt-dlp error: %s", msg)


def base_opts(**overrides: Any) -> dict[str, Any]:
    s = get_settings()
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "extractor_retries": 2,
        "cachedir": False,
        "logger": _YDLLogger(),
    }
    if s.yt_proxy:
        opts["proxy"] = s.yt_proxy
    if s.yt_cookies_file and os.path.exists(s.yt_cookies_file):
        opts["cookiefile"] = s.yt_cookies_file
    opts.update(overrides)
    return opts


def with_retries(fn: Callable[[], T], what: str) -> T:
    """Run fn with exponential backoff. Permanent errors (private, removed...) are not retried."""
    s = get_settings()
    attempts = max(1, s.retry_attempts)
    last: APIError | None = None
    for i in range(attempts):
        try:
            return fn()
        except PERMANENT_ERRORS:
            raise
        except APIError as exc:
            last = exc
        except Exception as exc:  # yt-dlp DownloadError / ExtractorError / network errors
            last = classify_ytdlp_error(str(exc))
            if isinstance(last, PERMANENT_ERRORS):
                raise last from exc
        if i < attempts - 1:
            delay = (s.retry_backoff ** i) + random.uniform(0, 0.5)
            log_event(log, "retrying", what=what, attempt=i + 1, delay=round(delay, 2), error=str(last))
            time.sleep(delay)
    raise last or UpstreamBlocked(f"{what} failed")


def extract_info(video_url: str, **overrides: Any) -> dict[str, Any]:
    """Metadata-only extraction (no download)."""
    import yt_dlp  # lazy

    def _run() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(base_opts(skip_download=True, **overrides)) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return ydl.sanitize_info(info) if info else {}

    return with_retries(_run, "extract_info")


def download(video_url: str, out_dir: str, fmt: str, **overrides: Any) -> str:
    """Download one format into out_dir; returns the resulting file path."""
    import yt_dlp  # lazy

    def _run() -> str:
        # Each download gets its own folder, so the audio .wav can never be mistaken for the video.
        os.makedirs(out_dir, exist_ok=True)
        dest = tempfile.mkdtemp(prefix="dl-", dir=out_dir)
        opts = base_opts(format=fmt, outtmpl=os.path.join(dest, "%(id)s.%(ext)s"), **overrides)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(video_url, download=True)
        files = [os.path.join(dest, f) for f in os.listdir(dest) if not f.endswith(".part")]
        if not files:
            raise UpstreamBlocked("Download produced no file.")
        return max(files, key=os.path.getsize)

    return with_retries(_run, f"download:{fmt}")
