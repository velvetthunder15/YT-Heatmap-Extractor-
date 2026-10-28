"""FastAPI app: fast path (GET /v1/heatmap), async jobs (/v1/jobs), health, docs."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, jobs
from .cache import cache_no_official, get_cached, get_redis, known_no_official, set_cached
from .config import get_settings
from .errors import APIError, InvalidURL, classify_ytdlp_error, UpstreamBlocked, VideoTooLong
from .logging_setup import log_event, setup_logging
from .pipeline import official_data, render_result
from .urls import extract_video_id

settings = get_settings()
setup_logging(settings.log_level)
log = logging.getLogger("api")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Find the most and least engaging segments of any YouTube video. Uses YouTube's official "
        "'Most replayed' data when it exists, otherwise a clearly labelled heuristic estimate."
    ),
)

if settings.cors_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_origin_regex=settings.cors_localhost_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )


# ------------------------------------------------------------- errors ------
def _err(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(APIError)
async def api_error_handler(_: Request, exc: APIError):
    headers = {"Retry-After": "60"} if exc.status == 429 else None
    return JSONResponse(exc.to_dict(), status_code=exc.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("query", "body"))
    return _err("validation_error", f"{loc}: {first.get('msg', 'invalid request')}", 422)


@app.exception_handler(StarletteHTTPException)
async def http_handler(_: Request, exc: StarletteHTTPException):
    return _err("not_found" if exc.status_code == 404 else "http_error", str(exc.detail), exc.status_code)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    if type(exc).__module__.startswith("yt_dlp"):  # a YouTube error that slipped past the typed mapping
        mapped = classify_ytdlp_error(str(exc))
        return _err(mapped.code, mapped.message, mapped.status)
    log.exception("unhandled")
    return _err("internal_error", "Internal server error.", 500)


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    t0 = time.time()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers.setdefault("Cache-Control", "no-store")  # results are per-key; never cache them in shared proxies
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    log_event(log, "request", rid=rid, method=request.method, path=request.url.path,
              status=response.status_code, ms=int((time.time() - t0) * 1000))
    return response


# --------------------------------------------------------------- auth ------
def _owner(key: auth.ApiKey | None) -> str:
    return key.key_hash if key else "anonymous"


def _auth(count_quota: bool):
    def dep(response: Response, x_api_key: Annotated[str | None, Header()] = None) -> auth.ApiKey | None:
        if not settings.require_api_key:
            return None
        r = get_redis()
        key = auth.lookup_key(r, x_api_key)
        for k, v in auth.enforce_limits(r, key, count_quota).items():
            response.headers[k] = v
        return key
    return dep


# ------------------------------------------------------------- models ------
class JobRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or ID")
    top: int = Field(5, ge=0, le=50)
    bottom: int = Field(5, ge=0, le=50)
    window: int | None = Field(None, description="Window size in seconds for estimated mode")
    force_estimate: bool = Field(False, description="Skip official data and always estimate")
    webhook_url: str | None = Field(None, description="https URL POSTed with the result on completion")


class JobAccepted(BaseModel):
    job_id: str
    status: str
    status_url: str


def _status_url(request: Request, job_id: str) -> str:
    base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/v1/jobs/{job_id}"


def _clamp(top: int, bottom: int, window: int | None) -> tuple[int, int, int]:
    top, bottom = min(top, settings.max_top), min(bottom, settings.max_top)
    w = window or settings.window_seconds
    if not settings.min_window_seconds <= w <= settings.max_window_seconds:
        raise InvalidURL(
            f"window must be between {settings.min_window_seconds} and {settings.max_window_seconds} seconds.",
            code="validation_error", status=422,
        )
    return top, bottom, w


# ------------------------------------------------------------- routes ------
@app.get("/health", tags=["meta"])
def health():
    try:
        get_redis().ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    body = {"status": "ok" if redis_ok else "degraded", "redis": redis_ok, "version": app.version}
    return JSONResponse(body, status_code=200 if redis_ok else 503)


@app.get("/v1/heatmap", tags=["heatmap"], responses={202: {"model": JobAccepted}})
async def get_heatmap(
    request: Request,
    url: Annotated[str, Query(description="YouTube video URL or ID")],
    top: Annotated[int, Query(ge=0, le=50)] = 5,
    bottom: Annotated[int, Query(ge=0, le=50)] = 5,
    window: Annotated[int | None, Query()] = None,
    force_estimate: bool = False,
    key: auth.ApiKey | None = Depends(_auth(count_quota=True)),
):
    """Fast path. Returns 200 with official or cached data immediately. When only an
    estimate is possible, a job is queued and 202 {job_id, status_url} is returned."""
    video_id = extract_video_id(url)
    top, bottom, w = _clamp(top, bottom, window)
    r = get_redis()

    data = get_cached(r, video_id, w, force_estimate)
    if data:
        return {**render_result(data, top, bottom), "cached": True}

    if not force_estimate and not known_no_official(r, video_id):
        from .sources.official import fetch_metadata

        try:
            info = await asyncio.wait_for(asyncio.to_thread(fetch_metadata, video_id), settings.official_timeout)
            data = await asyncio.wait_for(asyncio.to_thread(official_data, video_id, info), settings.official_timeout)
        except asyncio.TimeoutError:
            raise UpstreamBlocked("Timed out talking to YouTube. Try again, or use POST /v1/jobs.")
        if data:
            set_cached(r, data)
            return {**render_result(data, top, bottom), "cached": False}
        cache_no_official(r, video_id)
        duration = float(info.get("duration") or 0)
        if duration > settings.max_estimate_duration:
            raise VideoTooLong(
                f"No official heatmap, and the video ({int(duration // 60)} min) exceeds the "
                f"{settings.max_estimate_duration // 60} min limit for estimated mode."
            )

    job_id = jobs.enqueue(r, video_id, top, bottom, w, force_estimate, None, _owner(key))
    return JSONResponse(
        {
            "job_id": job_id,
            "status": "queued",
            "status_url": _status_url(request, job_id),
            "message": "No official heatmap is available; an estimate is being computed.",
        },
        status_code=202,
    )


@app.post("/v1/jobs", tags=["jobs"], status_code=202, response_model=JobAccepted)
def create_job(
    body: JobRequest,
    request: Request,
    key: auth.ApiKey | None = Depends(_auth(count_quota=True)),
):
    """Slow path: queue a full analysis (official first unless force_estimate)."""
    video_id = extract_video_id(body.url)
    top, bottom, w = _clamp(body.top, body.bottom, body.window)
    webhook = jobs.validate_webhook_url(body.webhook_url) if body.webhook_url else None
    job_id = jobs.enqueue(get_redis(), video_id, top, bottom, w, body.force_estimate, webhook, _owner(key))
    return JobAccepted(job_id=job_id, status="queued", status_url=_status_url(request, job_id))


@app.get("/v1/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str, key: auth.ApiKey | None = Depends(_auth(count_quota=False))):
    """Poll a job: status is queued | processing | done | failed, with progress 0..1."""
    return jobs.job_status(get_redis(), job_id, _owner(key))
