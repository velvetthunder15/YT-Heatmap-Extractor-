"""Async jobs on RQ: enqueue, run (with progress + global concurrency cap), webhooks."""
from __future__ import annotations

import ipaddress
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import redis
from rq import Queue, get_current_job
from rq.job import Job, JobStatus

from .config import get_settings
from .errors import APIError, InvalidURL, JobNotFound, UpstreamBlocked
from .logging_setup import log_event

log = logging.getLogger(__name__)
QUEUE_NAME = "heatmap"
SEM_KEY = "sem:heavy-jobs"


def get_queue(r: redis.Redis) -> Queue:
    return Queue(QUEUE_NAME, connection=r)


# ------------------------------------------------------------ webhooks -----
def validate_webhook_url(url: str) -> str:
    """https only, public addresses only (SSRF guard)."""
    s = get_settings()
    if not s.allow_webhooks:
        raise InvalidURL("Webhooks are disabled on this server.")
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise InvalidURL("webhook_url must be a plain https:// URL.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise InvalidURL("webhook_url host does not resolve.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise InvalidURL("webhook_url must point to a public address.")
    return url


def send_webhook(url: str, payload: dict[str, Any]) -> None:
    import httpx

    s = get_settings()
    try:
        validate_webhook_url(url)  # re-check at send time (DNS may have changed)
    except InvalidURL as exc:
        log_event(log, "webhook_rejected", error=exc.message)
        return
    for attempt in range(3):
        try:
            with httpx.Client(timeout=s.webhook_timeout, follow_redirects=False) as c:
                resp = c.post(url, json=payload, headers={"User-Agent": "yt-heatmap-extractor/1.0"})
            if resp.status_code < 500:
                return
        except Exception as exc:
            log_event(log, "webhook_failed", attempt=attempt + 1, error=str(exc)[:200])
        time.sleep(2**attempt)


# ----------------------------------------------------- concurrency cap -----
class GlobalSemaphore:
    """Cluster-wide cap on heavy jobs, shared by every worker container via Redis."""

    def __init__(self, r: redis.Redis, limit: int, wait_timeout: float = 600):
        self.r, self.limit, self.wait_timeout = r, limit, wait_timeout

    def __enter__(self):
        deadline = time.time() + self.wait_timeout
        while True:
            n = self.r.incr(SEM_KEY)
            self.r.expire(SEM_KEY, get_settings().job_timeout + 60)  # self-heals after crashes
            if n <= self.limit:
                return self
            self.r.decr(SEM_KEY)
            if time.time() > deadline:
                raise UpstreamBlocked("Server is busy; processing capacity unavailable. Try again later.")
            time.sleep(2)

    def __exit__(self, *exc):
        if int(self.r.decr(SEM_KEY)) < 0:
            self.r.set(SEM_KEY, 0)
        return False


# --------------------------------------------------------------- run -------
def _progress(p: float, message: str) -> None:
    job = get_current_job()
    if job:
        job.meta["progress"] = round(min(max(p, 0.0), 1.0), 2)
        job.meta["stage"] = message
        job.save_meta()


def run_heatmap_job(video_id: str, top: int, bottom: int, window: int, force_estimate: bool, webhook_url: str | None) -> dict[str, Any]:
    """Executed by the RQ worker. Returns the API response body; errors become {error}."""
    from .cache import cache_no_official, get_cached, get_redis, set_cached
    from .pipeline import build_heatmap, render_result

    r = get_redis()
    job = get_current_job()
    job_id = job.id if job else None
    started = time.time()
    try:
        _progress(0.01, "starting")
        data = get_cached(r, video_id, window, force_estimate)
        if data is None:
            with GlobalSemaphore(r, get_settings().global_max_jobs):
                data = build_heatmap(video_id, window, force_estimate, redis=r, progress=_progress)
            if data.source == "estimated" and not force_estimate:
                cache_no_official(r, video_id)
            set_cached(r, data)
        result = render_result(data, top, bottom)
        outcome: dict[str, Any] = {"ok": True, "result": result}
    except APIError as exc:
        outcome = {"ok": False, **exc.to_dict()}
    except Exception as exc:  # never leak stack traces to clients
        log.exception("job crashed")
        outcome = {"ok": False, "error": {"code": "internal_error", "message": "Processing failed unexpectedly."}}
        log_event(log, "job_crashed", job_id=job_id, error=str(exc)[:200])
    finally:
        r.delete(f"inflight:{video_id}:{window}:{int(force_estimate)}")

    _progress(1.0, "done" if outcome["ok"] else "failed")
    log_event(log, "job_finished", job_id=job_id, video_id=video_id, ok=outcome["ok"], seconds=round(time.time() - started, 1))
    if webhook_url:
        payload = {"job_id": job_id, "status": "done" if outcome["ok"] else "failed"}
        payload.update({"result": outcome["result"]} if outcome["ok"] else {"error": outcome["error"]})
        send_webhook(webhook_url, payload)
    return outcome


def enqueue(r: redis.Redis, video_id: str, top: int, bottom: int, window: int, force_estimate: bool, webhook_url: str | None, owner: str) -> str:
    """Enqueue (or join an identical in-flight job, when no webhook is attached)."""
    s = get_settings()
    inflight_key = f"inflight:{video_id}:{window}:{int(force_estimate)}"
    if not webhook_url:
        existing = r.get(inflight_key)
        if existing:
            job_id = existing.decode()
            try:
                job = Job.fetch(job_id, connection=r)
                if job.get_status() in (JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED, JobStatus.SCHEDULED) and job.meta.get("owner") == owner and job.args[1:3] == (top, bottom):
                    return job_id
            except Exception:
                pass
    job = get_queue(r).enqueue(
        run_heatmap_job,
        args=(video_id, top, bottom, window, force_estimate, webhook_url),
        job_timeout=s.job_timeout,
        result_ttl=s.job_result_ttl,
        failure_ttl=s.job_result_ttl,
        meta={"owner": owner, "progress": 0.0, "stage": "queued", "video_id": video_id},
    )
    r.set(inflight_key, ex=s.job_timeout, value=job.id)
    return job.id


_STATUS_MAP = {
    JobStatus.QUEUED: "queued",
    JobStatus.DEFERRED: "queued",
    JobStatus.SCHEDULED: "queued",
    JobStatus.STARTED: "processing",
    JobStatus.FINISHED: "done",
    JobStatus.FAILED: "failed",
    JobStatus.STOPPED: "failed",
    JobStatus.CANCELED: "failed",
}


def job_status(r: redis.Redis, job_id: str, owner: str) -> dict[str, Any]:
    try:
        job = Job.fetch(job_id, connection=r)
    except Exception as exc:
        raise JobNotFound("Job not found or expired.") from exc
    if job.meta.get("owner") != owner:
        raise JobNotFound("Job not found or expired.")  # don't reveal other users' jobs
    status = _STATUS_MAP.get(job.get_status(), "queued")
    body: dict[str, Any] = {
        "job_id": job.id,
        "status": status,
        "progress": job.meta.get("progress", 0.0),
        "stage": job.meta.get("stage"),
        "result": None,
    }
    if status == "done":
        out = job.return_value() or {}
        if out.get("ok"):
            body["result"] = out["result"]
        else:
            body["status"] = "failed"
            body["error"] = out.get("error")
    elif status == "failed":
        body["error"] = {"code": "internal_error", "message": "Job failed or timed out."}
    return body
