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


class VideoMembersOnly(APIError):
    code, status = "video_members_only", 403


class VideoPremiumOnly(APIError):
    code, status = "video_premium_only", 403


class VideoNeedsSignIn(APIError):
    code, status = "video_needs_sign_in", 403


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
PERMANENT_ERRORS = (InvalidURL, VideoPrivate, VideoMembersOnly, VideoPremiumOnly, VideoNeedsSignIn, AgeRestricted, VideoUnavailable, VideoLive, VideoTooLong)


PRIVATE_MSG = "This video is private, so it can't be analysed. Only videos anyone can watch work (public or unlisted)."
MEMBERS_MSG = "This video is for channel members only, so it can't be analysed. Only videos anyone can watch work (public or unlisted)."
PREMIUM_MSG = "This video needs YouTube Premium, so it can't be analysed."
SIGN_IN_MSG = "YouTube only shows this video to signed-in viewers, so it can't be analysed."
AGE_MSG = "This video is age-restricted and can't be analysed without cookies (YT_COOKIES_FILE)."
UNAVAILABLE_MSG = "This video is unavailable. It may have been removed, or the link may be wrong."


def _youtube_reason(msg: str) -> str:
    """'ERROR: [youtube] abc123: Reason text. Use --cookies...' -> 'Reason text.'"""
    import re

    text = re.sub(r"^\s*(ERROR:\s*)?(\[[^\]]+\]\s*)?([\w-]{6,}:\s*)?", "", msg.strip())
    return re.split(r"\s*(Use --cookies|See\s+https?://|Please report this issue)", text)[0].strip()[:200]


def classify_ytdlp_error(msg: str) -> APIError:
    """Map a yt-dlp / YouTube error string onto one of our typed errors."""
    m = msg.lower()
    if "private video" in m or "video is private" in m:
        return VideoPrivate(PRIVATE_MSG)
    if ("members-only" in m or "members only" in m or "join this channel" in m
            or "channel's members" in m or "channel members" in m or "members on level" in m):
        return VideoMembersOnly(MEMBERS_MSG)
    if "youtube premium" in m or "premium members" in m or "music premium" in m:
        return VideoPremiumOnly(PREMIUM_MSG)
    if "confirm your age" in m or "age-restricted" in m or "age restricted" in m or "inappropriate for some users" in m:
        return AgeRestricted(AGE_MSG)
    if "not a bot" in m or "http error 429" in m or "too many requests" in m or ("403" in m and "forbidden" in m):
        return UpstreamBlocked(
            "YouTube blocked the request from this server. Configure YT_PROXY or YT_COOKIES_FILE."
        )
    if "live event" in m or "is live" in m or "premieres in" in m or "premiere will begin" in m:
        return VideoLive("Live or upcoming videos are not supported.")
    if ("video unavailable" in m or "has been removed" in m or "does not exist" in m or "not available" in m
            or "terminated" in m or "no longer available" in m or "incomplete youtube id" in m):
        return VideoUnavailable(UNAVAILABLE_MSG)
    if "sign in" in m or "login required" in m or "requires authentication" in m:
        return VideoNeedsSignIn(SIGN_IN_MSG)
    reason = _youtube_reason(msg)
    return UpstreamBlocked(f"YouTube returned an error: {reason}" if reason else "YouTube returned an error.")
