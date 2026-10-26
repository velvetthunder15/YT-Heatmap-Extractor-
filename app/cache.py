"""Redis connection + heatmap cache keyed by video ID.

Official results: CACHE_TTL_OFFICIAL (24h). Estimated: CACHE_TTL_ESTIMATED (7 days),
keyed by window size too. We cache the full analysis, so any top/bottom is served
from one entry.
"""
from __future__ import annotations

import json
from functools import lru_cache

import redis

from .config import get_settings
from .pipeline import HeatmapData


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url)


def _key_official(video_id: str) -> str:
    return f"hm:official:{video_id}"


def _key_estimated(video_id: str, window: float) -> str:
    return f"hm:estimated:{video_id}:{int(window)}"


def get_cached(r: redis.Redis, video_id: str, window: float, force_estimate: bool = False) -> HeatmapData | None:
    keys = [] if force_estimate else [_key_official(video_id)]
    keys.append(_key_estimated(video_id, window))
    for k in keys:
        raw = r.get(k)
        if raw:
            return HeatmapData.from_dict(json.loads(raw))
    return None


def set_cached(r: redis.Redis, data: HeatmapData) -> None:
    s = get_settings()
    if data.source == "official":
        r.set(_key_official(data.video_id), ex=s.cache_ttl_official, value=json.dumps(data.to_dict()))
    else:
        r.set(_key_estimated(data.video_id, data.window or s.window_seconds), json.dumps(data.to_dict()), ex=s.cache_ttl_estimated)


def cache_no_official(r: redis.Redis, video_id: str) -> None:
    """Remember for an hour that a video has no official heatmap (skips re-checking)."""
    r.set(f"hm:no-official:{video_id}", ex=3600, value="1")


def known_no_official(r: redis.Redis, video_id: str) -> bool:
    return bool(r.exists(f"hm:no-official:{video_id}"))
