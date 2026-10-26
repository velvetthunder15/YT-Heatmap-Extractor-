"""API tests with fakeredis: auth, rate limits, error format, cache fast path, job queueing."""
import fakeredis
import pytest
from fastapi.testclient import TestClient

import app.cache as cache_mod
from app import auth
from app.config import get_settings


@pytest.fixture
def client(monkeypatch):
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: r)
    import app.main as main
    monkeypatch.setattr(main, "get_redis", lambda: r)
    c = TestClient(main.app)
    c.r = r
    c.key = auth.create_key(r, "tester", rate_limit_per_min=3, daily_quota=100)
    return c


def test_health(client):
    assert client.get("/health").json()["redis"] is True


def test_missing_key(client):
    res = client.get("/v1/heatmap", params={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_invalid_url_error_format(client):
    res = client.get("/v1/heatmap", params={"url": "https://evil.com/x"}, headers={"X-API-Key": client.key})
    assert res.status_code == 400
    assert res.json() == {"error": {"code": "invalid_url", "message": res.json()["error"]["message"]}}


def test_rate_limited(client):
    h = {"X-API-Key": client.key}
    codes = [client.get("/v1/heatmap", params={"url": "bad"}, headers=h).status_code for _ in range(4)]
    assert codes[-1] == 429


def test_cached_official_served_fast(client):
    from tests.test_pipeline import official_hit
    data = official_hit("dQw4w9WgXcQ", {})
    cache_mod.set_cached(client.r, data)
    res = client.get("/v1/heatmap", params={"url": "https://youtu.be/dQw4w9WgXcQ", "top": 2}, headers={"X-API-Key": client.key})
    assert res.status_code == 200
    body = res.json()
    assert body["cached"] is True and body["source"] == "official"
    assert len(body["most_engaging"]) == 2


def test_post_job_and_poll(client):
    h = {"X-API-Key": client.key}
    res = client.post("/v1/jobs", json={"url": "dQw4w9WgXcQ", "force_estimate": True}, headers=h)
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    assert res.json()["status_url"].endswith(f"/v1/jobs/{job_id}")
    poll = client.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert poll["status"] == "queued"
    # another key cannot see this job
    other = auth.create_key(client.r, "other")
    assert client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": other}).status_code == 404


def test_webhook_ssrf_blocked(client):
    res = client.post("/v1/jobs", json={"url": "dQw4w9WgXcQ", "webhook_url": "https://127.0.0.1/hook"},
                      headers={"X-API-Key": client.key})
    assert res.status_code == 400


def test_bad_window(client):
    res = client.get("/v1/heatmap", params={"url": "dQw4w9WgXcQ", "window": 1}, headers={"X-API-Key": client.key})
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"


def test_worker_runs_job_end_to_end(client, monkeypatch):
    """Run a queued job in-process with a fake pipeline and read the result back."""
    from rq import SimpleWorker
    import app.pipeline as pipeline
    from tests.test_pipeline import INFO, fake_sources, official_miss

    real_build = pipeline.build_heatmap
    monkeypatch.setattr(pipeline, "build_heatmap", lambda vid, w, f, redis=None, progress=None: real_build(
        vid, w, f, redis=redis, progress=progress, info=INFO, official_fn=official_miss, sources=fake_sources()))
    h = {"X-API-Key": client.key}
    job_id = client.post("/v1/jobs", json={"url": "dQw4w9WgXcQ", "top": 2, "bottom": 2}, headers=h).json()["job_id"]
    SimpleWorker(["heatmap"], connection=client.r).work(burst=True)
    body = client.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert body["status"] == "done" and body["progress"] == 1.0
    assert body["result"]["source"] == "estimated" and len(body["result"]["most_engaging"]) == 2
    # result is now cached: the fast path answers with 200
    res = client.get("/v1/heatmap", params={"url": "dQw4w9WgXcQ"}, headers=h)
    assert res.status_code == 200 and res.json()["cached"] is True
