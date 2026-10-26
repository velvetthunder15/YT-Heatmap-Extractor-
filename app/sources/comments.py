"""Signal: timestamps mentioned in comments ("3:42", "1:02:10").

Comments come from the YouTube Data API v3 when YT_API_KEY is set (quota tracked in
Redis, 1 unit per page) and fall back to yt-dlp comment scraping when the key is
missing, the quota is spent, or the API errors.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..config import get_settings
from ..logging_setup import log_event
from ..urls import canonical_url

log = logging.getLogger(__name__)

TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?![\d:])")


@dataclass
class CommentSignal:
    curve: list[float]  # raw density per window (not yet normalised)
    timestamped_comments: int
    total_comments: int


def parse_timestamps(text: str, duration: float | None = None) -> list[int]:
    """All distinct in-range timestamps (seconds) mentioned in a comment."""
    out: list[int] = []
    for h, m, s in TS_RE.findall(text or ""):
        secs = int(h or 0) * 3600 + int(m) * 60 + int(s)
        if h == "" and int(m) > 59:
            continue
        if duration is not None and secs > duration:
            continue
        if secs not in out:
            out.append(secs)
    return out


def density_curve(
    mentions: Iterable[tuple[int, float]], windows: list[tuple[float, float]], spread: float
) -> list[float]:
    """Spread each (timestamp, weight) mention uniformly over [t-spread, t+spread] and
    accumulate the overlap with every window."""
    curve = [0.0] * len(windows)
    width = 2 * spread if spread > 0 else 1.0
    for t, weight in mentions:
        a, b = t - spread, t + spread
        for i, (ws, we) in enumerate(windows):
            if we <= a:
                continue
            if ws >= b:
                break
            overlap = min(b, we) - max(a, ws)
            if overlap > 0:
                curve[i] += weight * overlap / width
    return curve


# ----------------------------------------------------------- fetching -------
def _quota_key() -> str:
    # The Data API quota resets at midnight Pacific time.
    pacific_now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8)
    return f"ytapi:quota:{pacific_now:%Y%m%d}"


def _quota_take(redis, units: int) -> bool:
    s = get_settings()
    if redis is None:
        return True
    key = _quota_key()
    used = redis.incrby(key, units)
    redis.expire(key, 2 * 86400)
    if used > s.yt_api_daily_quota:
        redis.decrby(key, units)
        return False
    return True


def _from_data_api(video_id: str, redis) -> list[dict[str, Any]] | None:
    import httpx

    s = get_settings()
    comments: list[dict[str, Any]] = []
    page_token = None
    with httpx.Client(timeout=15) as client:
        while len(comments) < s.max_comments:
            if not _quota_take(redis, 1):
                log_event(log, "ytapi_quota_exhausted", video_id=video_id)
                return comments or None  # degrade to scraping if nothing fetched
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": 100,
                "order": "relevance",
                "textFormat": "plainText",
                "key": s.yt_api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            r = client.get("https://www.googleapis.com/youtube/v3/commentThreads", params=params)
            if r.status_code == 403 and "commentsDisabled" in r.text:
                return []
            if r.status_code != 200:
                log_event(log, "ytapi_error", video_id=video_id, status=r.status_code)
                return comments or None
            data = r.json()
            for item in data.get("items", []):
                sn = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({"text": sn.get("textDisplay", ""), "like_count": sn.get("likeCount", 0)})
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return comments


def _from_ytdlp(video_id: str) -> list[dict[str, Any]]:
    from .. import ytdl

    s = get_settings()
    info = ytdl.extract_info(
        canonical_url(video_id),
        getcomments=True,
        extractor_args={"youtube": {"max_comments": [str(s.max_comments), "all", "0", "0"], "comment_sort": ["top"]}},
    )
    return info.get("comments") or []


def fetch_comments(video_id: str, redis=None) -> list[dict[str, Any]]:
    s = get_settings()
    if s.yt_api_key:
        try:
            got = _from_data_api(video_id, redis)
            if got is not None:
                return got
        except Exception as exc:
            log_event(log, "ytapi_failed", video_id=video_id, error=str(exc))
    return _from_ytdlp(video_id)


def comment_signal(
    video_id: str, duration: float, windows: list[tuple[float, float]], redis=None
) -> CommentSignal | None:
    """Returns None when there are too few timestamped comments to be meaningful."""
    s = get_settings()
    comments = fetch_comments(video_id, redis)
    mentions: list[tuple[int, float]] = []
    n_ts = 0
    for c in comments:
        stamps = parse_timestamps(c.get("text", ""), duration)
        if not stamps:
            continue
        n_ts += 1
        weight = 1.0 + math.log1p(max(0, int(c.get("like_count") or 0)))
        mentions.extend((t, weight) for t in stamps)
    if n_ts < s.min_timestamped_comments:
        log_event(log, "comments_skipped", video_id=video_id, timestamped=n_ts, total=len(comments))
        return None
    return CommentSignal(density_curve(mentions, windows, s.comment_spread_seconds), n_ts, len(comments))
