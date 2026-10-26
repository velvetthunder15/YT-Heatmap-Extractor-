"""Fallback-chain tests with fake sources (no network, no ffmpeg)."""
import pytest

from app.errors import NoDataAvailable, VideoTooLong
from app.pipeline import HeatmapData, build_heatmap, estimate_confidence, render_result
from app.scoring import Segment
from app.sources.comments import CommentSignal
from app.sources.official import parse_initial_data

INFO = {"title": "Test video", "duration": 100}


def official_hit(video_id, info):
    from dataclasses import asdict
    segs = [Segment(i * 10, (i + 1) * 10, v) for i, v in enumerate([0.2, 1.0, 0.4, 0.1, 0.3, 0.2, 0.6, 0.0, 0.5, 0.3])]
    return HeatmapData(video_id, "Test video", 100, "official", "high", "official", ["official_most_replayed"], {}, [asdict(s) for s in segs])


def official_miss(video_id, info):
    return None


def fake_sources(comments=True, transcript=True, audio=True, visual=True, n_ts=60):
    def c(vid, dur, windows, redis):
        if not comments:
            return None
        curve = [0.0] * len(windows); curve[3] = 5.0; curve[4] = 2.0
        return CommentSignal(curve, n_ts, 200)

    def t(vid, windows):
        return [float(i % 3) for i in range(len(windows))] if transcript else None

    def a(vid, windows, d):
        return [1.0 if i == 3 else 0.2 for i in range(len(windows))] if audio else None

    def v(vid, windows, d):
        if not visual:
            return None
        raise RuntimeError("scenedetect exploded")  # broken signal must be dropped, not fatal

    return {"comments": c, "transcript": t, "audio": a, "visual": v}


def test_official_preferred():
    data = build_heatmap("vid12345678", 10, info=INFO, official_fn=official_hit, sources=fake_sources())
    assert data.source == "official" and data.confidence == "high"


def test_falls_back_to_estimated_and_drops_broken_signal():
    data = build_heatmap("vid12345678", 10, info=INFO, official_fn=official_miss, sources=fake_sources())
    assert data.source == "estimated"
    assert data.signals_used == ["comments", "transcript", "audio"]  # visual crashed -> dropped
    assert abs(sum(data.weights.values()) - 1) < 1e-6
    assert data.confidence == "high"
    res = render_result(data, 2, 2)
    assert res["is_estimate"] is True and "heuristic" in res["disclaimer"]
    assert res["most_engaging"][0]["start"] == 30  # window 3 has comments + audio peak
    assert res["most_engaging"][0]["signals"][0]["name"] == "comments"
    assert res["most_engaging"][0]["link"].endswith("?t=30")


def test_force_estimate_skips_official():
    data = build_heatmap("vid12345678", 10, force_estimate=True, info=INFO, official_fn=official_hit, sources=fake_sources())
    assert data.source == "estimated"


def test_low_confidence_without_comments():
    data = build_heatmap("vid12345678", 10, info=INFO, official_fn=official_miss,
                         sources=fake_sources(comments=False, transcript=False))
    assert data.signals_used == ["audio"]
    assert data.confidence == "low"


def test_everything_fails_raises_clear_error():
    with pytest.raises(NoDataAvailable):
        build_heatmap("vid12345678", 10, info=INFO, official_fn=official_miss,
                      sources=fake_sources(False, False, False, False))


def test_too_long_for_estimate():
    with pytest.raises(VideoTooLong):
        build_heatmap("vid12345678", 10, info={"duration": 99999}, official_fn=official_miss, sources=fake_sources())


def test_official_render():
    data = official_hit("vid12345678", INFO)
    res = render_result(data, 3, 3)
    assert res["source"] == "official"
    assert res["most_engaging"][0]["start_hms"] == "00:00:10"
    assert res["most_engaging"][0]["type"] == "peak"
    assert res["least_engaging"][0]["type"] == "drop-off"
    assert len(res["full_heatmap"]) == 10


def test_confidence_levels():
    assert estimate_confidence(["comments", "transcript", "audio"], 80)[0] == "high"
    assert estimate_confidence(["comments", "audio"], 12)[0] == "medium"
    assert estimate_confidence(["audio"], 0)[0] == "low"


def test_parse_initial_data_both_formats():
    legacy = {"x": {"heatMarkers": [
        {"heatMarkerRenderer": {"timeRangeStartMillis": 0, "markerDurationMillis": 5000, "heatMarkerIntensityScoreNormalized": 0.2}},
        {"heatMarkerRenderer": {"timeRangeStartMillis": 5000, "markerDurationMillis": 5000, "heatMarkerIntensityScoreNormalized": 1}},
    ]}}
    segs = parse_initial_data(legacy)
    assert [(s.start, s.end, s.score) for s in segs] == [(0, 5, 0.2), (5, 10, 1.0)]
    newer = {"frameworkUpdates": {"m": [{"markers": [
        {"startMillis": "0", "durationMillis": "4000", "intensityScoreNormalized": 0.5},
        {"startMillis": "4000", "durationMillis": "4000", "intensityScoreNormalized": 0.9},
    ]}]}}
    assert [s.score for s in parse_initial_data(newer)] == [0.5, 0.9]
    assert parse_initial_data({"nothing": 1}) is None
