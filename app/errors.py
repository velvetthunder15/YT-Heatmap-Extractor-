"""Typed API errors. Every error leaves the API as {"error": {"code", "message"}}."""
from __future__ import annotations


class APIError(Exception):
    code = "internal_error"
    status = 500

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class InvalidURL(APIError):
    code, status = "invalid_url", 400


class Unauthorized(APIError):
    code, status = "unauthorized", 401


class VideoPrivate(APIError):
    code, status = "video_private", 403


class AgeRestricted(APIError):
    code, status = "video_age_restricted", 403


class VideoUnavailable(APIError):
    code, status = "video_unavailable", 404


class VideoLive(APIError):
    code, status = "video_live", 422


class VideoTooLong(APIError):
    code, status = "video_too_long", 422


class NoDataAvailable(APIError):
    code, status = "no_data_available", 422


class RateLimited(APIError):
    code, status = "rate_limited", 429


class QuotaExceeded(APIError):
    code, status = "quota_exceeded", 429


class UpstreamBlocked(APIError):
    code, status = "upstream_blocked", 502


class JobNotFound(APIError):
    code, status = "job_not_found", 404


# Errors that will not change on retry (used by the backoff helper).
PERMANENT_ERRORS = (InvalidURL, VideoPrivate, AgeRestricted, VideoUnavailable, VideoLive, VideoTooLong)


def classify_ytdlp_error(msg: str) -> APIError:
    """Map a yt-dlp / YouTube error string onto one of our typed errors."""
    m = msg.lower()
    if "private video" in m:
        return VideoPrivate("This video is private.")
    if "confirm your age" in m or "age-restricted" in m or "inappropriate for some users" in m:
        return AgeRestricted("This video is age-restricted and cannot be analysed without cookies.")
    if "not a bot" in m or "http error 429" in m or "too many requests" in m or ("403" in m and "forbidden" in m):
        return UpstreamBlocked(
            "YouTube blocked the request from this server. Configure YT_PROXY or YT_COOKIES_FILE."
        )
    if "live event" in m or "is live" in m or "premieres in" in m:
        return VideoLive("Live or upcoming videos are not supported.")
    if "video unavailable" in m or "has been removed" in m or "does not exist" in m or "not available" in m:
        return VideoUnavailable("This video is unavailable.")
    return UpstreamBlocked(f"Upstream error from YouTube: {msg[:200]}")
