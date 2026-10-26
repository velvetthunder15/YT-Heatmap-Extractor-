"""Source 1: YouTube's official "Most replayed" heatmap.

Primary: yt-dlp metadata (info["heatmap"]). Fallback: parse ytInitialData from the
watch page (old `heatMarkers` and newer `macroMarkersListEntity` formats).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import get_settings
from ..errors import AgeRestricted, VideoLive, VideoPrivate, VideoUnavailable
from ..logging_setup import log_event
from ..scoring import Segment
from ..urls import canonical_url
from .. import ytdl

log = logging.getLogger(__name__)


def fetch_metadata(video_id: str) -> dict[str, Any]:
    """yt-dlp metadata for the video, with status checks that raise typed errors."""
    info = ytdl.extract_info(canonical_url(video_id))
    check_playable(info)
    return info


def check_playable(info: dict[str, Any]) -> None:
    if not info:
        raise VideoUnavailable("This video is unavailable.")
    live_status = info.get("live_status")
    if info.get("is_live") or live_status in ("is_live", "is_upcoming"):
        raise VideoLive("Live or upcoming videos are not supported.")
    availability = info.get("availability")
    if availability == "private":
        raise VideoPrivate("This video is private.")
    if availability == "needs_auth" or ((info.get("age_limit") or 0) >= 18 and not info.get("formats")):
        raise AgeRestricted("This video is age-restricted and cannot be analysed without cookies.")


def heatmap_from_info(info: dict[str, Any]) -> list[Segment] | None:
    raw = info.get("heatmap") or []
    segs = [
        Segment(float(p["start_time"]), float(p["end_time"]), float(p.get("value", 0.0)))
        for p in raw
        if p.get("start_time") is not None and p.get("end_time") is not None
    ]
    return _rescale(segs) if segs else None


# ------------------------------------------------- ytInitialData fallback ---
_INITIAL_DATA_RE = re.compile(r"(?:var\s+ytInitialData|window\[\"ytInitialData\"\])\s*=\s*(\{.+?\})\s*;\s*</script>", re.S)


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def parse_initial_data(data: dict[str, Any]) -> list[Segment] | None:
    """Find heat markers anywhere in ytInitialData (format varies between rollouts)."""
    segs: list[Segment] = []
    for node in _walk(data):
        # Legacy format: heatMarkers[].heatMarkerRenderer
        if "heatMarkerRenderer" in node:
            r = node["heatMarkerRenderer"]
            try:
                start = int(r["timeRangeStartMillis"]) / 1000
                dur = int(r["markerDurationMillis"]) / 1000
                segs.append(Segment(start, start + dur, float(r["heatMarkerIntensityScoreNormalized"])))
            except (KeyError, ValueError, TypeError):
                continue
        # Newer format: macroMarkersListEntity.markersList.markers[]
        elif "intensityScoreNormalized" in node and "startMillis" in node:
            try:
                start = int(node["startMillis"]) / 1000
                dur = int(node["durationMillis"]) / 1000
                segs.append(Segment(start, start + dur, float(node["intensityScoreNormalized"])))
            except (KeyError, ValueError, TypeError):
                continue
        if segs and len(segs) >= 100:
            break
    if not segs:
        return None
    # De-duplicate (the same markers can appear twice) and sort.
    uniq = {round(s.start, 3): s for s in segs}
    return _rescale(sorted(uniq.values(), key=lambda s: s.start))


def heatmap_from_watch_page(video_id: str) -> list[Segment] | None:
    import httpx

    s = get_settings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(proxy=s.yt_proxy or None, timeout=15, headers=headers, follow_redirects=False) as client:
        resp = client.get(canonical_url(video_id), params={"hl": "en"})
    if resp.status_code != 200:
        log_event(log, "watch_page_non_200", video_id=video_id, status=resp.status_code)
        return None
    m = _INITIAL_DATA_RE.search(resp.text)
    if not m:
        return None
    try:
        return parse_initial_data(json.loads(m.group(1)))
    except json.JSONDecodeError:
        return None


def _rescale(segs: list[Segment]) -> list[Segment]:
    """Official values are already 0..1 relative intensity; clamp defensively."""
    for s in segs:
        s.score = min(1.0, max(0.0, s.score))
    return segs


def get_official(video_id: str, info: dict[str, Any] | None) -> list[Segment] | None:
    """Return official segments or None if YouTube has no Most-replayed data."""
    if info:
        segs = heatmap_from_info(info)
        if segs:
            return segs
    try:
        return heatmap_from_watch_page(video_id)
    except Exception as exc:  # network issues -> treat as "no official data"
        log_event(log, "watch_page_failed", video_id=video_id, error=str(exc))
        return None
