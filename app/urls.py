"""Strict YouTube URL parsing.

Only YouTube hosts are accepted and only the 11-character video ID is ever passed
downstream. We always rebuild a canonical watch URL from the ID, so a caller can
never make the server fetch an arbitrary host (SSRF protection).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .errors import InvalidURL

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
}

MAX_URL_LENGTH = 2048


def extract_video_id(url: str) -> str:
    """Return the video ID from a YouTube URL (or a bare ID), else raise InvalidURL."""
    if not url or not isinstance(url, str):
        raise InvalidURL("A YouTube video URL is required.")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise InvalidURL("URL is too long.")

    # Bare video ID
    if VIDEO_ID_RE.match(url):
        return url

    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError as exc:  # pragma: no cover - urlparse rarely raises
        raise InvalidURL("Malformed URL.") from exc

    if parsed.scheme not in ("http", "https"):
        raise InvalidURL("Only http(s) YouTube URLs are accepted.")
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise InvalidURL("URLs with credentials or custom ports are not accepted.")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidURL("Only youtube.com and youtu.be URLs are accepted.")

    path = parsed.path or "/"
    candidate: str | None = None

    if host == "youtu.be":
        candidate = path.lstrip("/").split("/")[0]
    elif path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [None])[0]
    else:
        m = re.match(r"^/(?:shorts|embed|live|v|e)/([^/?#]+)", path)
        if m:
            candidate = m.group(1)

    if not candidate or not VIDEO_ID_RE.match(candidate):
        raise InvalidURL("Could not find a valid YouTube video ID in the URL.")
    return candidate


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def timestamp_link(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"
