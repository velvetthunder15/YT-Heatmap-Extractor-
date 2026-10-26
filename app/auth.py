"""API key auth (X-API-Key), per-key rate limits (per minute) and daily quotas.

Keys are never stored in plain text: we store HMAC-SHA256(API_KEY_PEPPER, key).
Keys live in Redis (`apikey:<hash>` -> JSON settings, managed with scripts/manage_keys.py)
or as static hashes in API_KEY_HASHES.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

import redis

from .config import get_settings
from .errors import QuotaExceeded, RateLimited, Unauthorized

KEY_PREFIX = "yhx_"


@dataclass
class ApiKey:
    key_hash: str
    name: str
    rate_limit_per_min: int
    daily_quota: int


def hash_key(raw: str) -> str:
    pepper = get_settings().api_key_pepper.encode()
    return hmac.new(pepper, raw.encode(), hashlib.sha256).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def create_key(r: redis.Redis, name: str, rate_limit_per_min: int | None = None, daily_quota: int | None = None) -> str:
    s = get_settings()
    raw = generate_key()
    record = {
        "name": name,
        "rate_limit_per_min": rate_limit_per_min or s.default_rate_limit_per_min,
        "daily_quota": daily_quota or s.default_daily_quota,
        "created": int(time.time()),
    }
    r.set(f"apikey:{hash_key(raw)}", json.dumps(record))
    return raw  # shown once, never stored


def revoke_key(r: redis.Redis, key_hash: str) -> bool:
    return bool(r.delete(f"apikey:{key_hash}"))


def lookup_key(r: redis.Redis, raw: str | None) -> ApiKey:
    s = get_settings()
    if not raw:
        raise Unauthorized("Missing X-API-Key header.")
    h = hash_key(raw)
    rec = r.get(f"apikey:{h}")
    if rec:
        d = json.loads(rec)
        return ApiKey(h, d.get("name", "key"), int(d["rate_limit_per_min"]), int(d["daily_quota"]))
    static = {x.strip().lower() for x in s.api_key_hashes.split(",") if x.strip()}
    if any(hmac.compare_digest(h, x) for x in static):
        return ApiKey(h, "static", s.default_rate_limit_per_min, s.default_daily_quota)
    raise Unauthorized("Invalid API key.")


def enforce_limits(r: redis.Redis, key: ApiKey, count_quota: bool = True) -> dict[str, str]:
    """Fixed-window rate limit per minute + daily quota (UTC). Returns rate-limit headers."""
    now = int(time.time())
    minute_key = f"rl:{key.key_hash}:{now // 60}"
    pipe = r.pipeline()
    pipe.incr(minute_key)
    pipe.expire(minute_key, 120)
    used_min = pipe.execute()[0]
    if used_min > key.rate_limit_per_min:
        raise RateLimited(f"Rate limit of {key.rate_limit_per_min} requests/minute exceeded. Retry in {60 - now % 60}s.")

    headers = {
        "X-RateLimit-Limit": str(key.rate_limit_per_min),
        "X-RateLimit-Remaining": str(max(0, key.rate_limit_per_min - used_min)),
    }
    if count_quota:
        day_key = f"quota:{key.key_hash}:{dt.datetime.now(dt.timezone.utc):%Y%m%d}"
        pipe = r.pipeline()
        pipe.incr(day_key)
        pipe.expire(day_key, 2 * 86400)
        used_day = pipe.execute()[0]
        if used_day > key.daily_quota:
            raise QuotaExceeded(f"Daily quota of {key.daily_quota} requests exceeded. Resets at 00:00 UTC.")
        headers["X-Quota-Remaining"] = str(max(0, key.daily_quota - used_day))
    return headers
