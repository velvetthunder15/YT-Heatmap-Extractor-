"""The fallback chain: official heatmap -> estimated heatmap -> clear error.

`build_heatmap` produces a cacheable `HeatmapData` (all segments + metadata);
`render_result` turns it into the API response for a given top/bottom, which is
cheap, so one cached analysis serves every top/bottom combination.
"""
from __future__ import annotations

import logging
import re
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .config import get_settings
from .errors import NoDataAvailable, VideoTooLong
from .logging_setup import log_event
from .scoring import (
    Segment,
    calibrate_shape,
    combine_signals,
    contributing_signals,
    make_windows,
    normalize,
    renormalize_weights,
    select_ranges,
    to_hms,
)
from .urls import timestamp_link

log = logging.getLogger(__name__)
ProgressFn = Callable[[float, str], None]

ESTIMATE_DISCLAIMER = (
    "Estimated from comments, captions, audio and visuals. This is a heuristic, not real viewer data."
)
_SIGNAL_LABELS = {"comments": "timestamped comments", "transcript": "captions", "audio": "audio", "visual": "visuals"}


def estimate_disclaimer(signals: list[str]) -> str:
    names = [_SIGNAL_LABELS.get(s, s) for s in signals]
    if not names:
        return ESTIMATE_DISCLAIMER
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Estimated from {joined}. This is a heuristic, not real viewer data."


@dataclass
class HeatmapData:
    video_id: str
    title: str | None
    duration: float | None
    source: str  # "official" | "estimated"
    confidence: str
    confidence_reason: str
    signals_used: list[str]
    weights: dict[str, float]
    segments: list[dict[str, Any]]  # serialised Segment
    window: float | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HeatmapData":
        return cls(**d)

    def segs(self) -> list[Segment]:
        return [Segment(**s) for s in self.segments]


# ------------------------------------------------------------ confidence ---
def estimate_confidence(signals: list[str], timestamped_comments: int) -> tuple[str, str]:
    n = len(signals)
    if "comments" in signals and timestamped_comments >= 50 and n >= 3:
        return "high", f"{timestamped_comments} timestamped comments plus {n - 1} other signals agree on the timeline."
    if ("comments" in signals and n >= 2) or ("transcript" in signals and n >= 3):
        detail = f"{timestamped_comments} timestamped comments" if "comments" in signals else "no comment timestamps"
        return "medium", f"{n} signals available ({', '.join(signals)}), {detail}."
    missing = "no usable comment timestamps" if "comments" not in signals else "few supporting signals"
    return "low", f"Only {n} signal(s) available ({', '.join(signals) or 'none'}), {missing}."


# ------------------------------------------------------------ official -----
def official_data(video_id: str, info: dict[str, Any] | None) -> HeatmapData | None:
    from .sources import official

    segs = official.get_official(video_id, info)
    if not segs:
        return None
    info = info or {}
    return HeatmapData(
        video_id=video_id,
        title=info.get("title"),
        duration=info.get("duration") or (segs[-1].end if segs else None),
        source="official",
        confidence="high",
        confidence_reason="YouTube's own 'Most replayed' data (relative replay intensity).",
        signals_used=["official_most_replayed"],
        weights={},
        segments=[asdict(s) for s in segs],
    )


# ------------------------------------------------------------ estimated ----
def estimated_data(
    video_id: str,
    info: dict[str, Any],
    window: float,
    redis=None,
    progress: ProgressFn | None = None,
    sources: dict[str, Callable[..., Any]] | None = None,
) -> HeatmapData:
    """Run every enabled signal, drop the unavailable ones, renormalise weights, combine.

    `sources` lets tests inject fake signal functions.
    """
    s = get_settings()
    duration = float(info.get("duration") or 0)
    if duration <= 0:
        raise NoDataAvailable("Video duration is unknown, so no heatmap can be estimated.")
    if duration > s.max_estimate_duration:
        raise VideoTooLong(
            f"Video is {int(duration // 60)} min; estimated mode is limited to {s.max_estimate_duration // 60} min."
        )

    progress = progress or (lambda p, m: None)
    windows = make_windows(duration, window)
    sources = sources or _default_sources()
    enabled = s.enabled_signals
    curves: dict[str, list[float]] = {}
    stats: dict[str, Any] = {"timestamped_comments": 0}
    skipped: dict[str, str] = {}

    os.makedirs(s.tmp_dir, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix=f"{video_id}-", dir=s.tmp_dir)
    try:
        order = ["comments", "transcript", "audio", "visual"]
        for i, name in enumerate(order):
            if not enabled.get(name, True) or name not in sources:
                skipped[name] = "disabled"
                continue
            progress(0.1 + 0.8 * i / len(order), f"analysing {name}")
            try:
                if name == "comments":
                    res = sources[name](video_id, duration, windows, redis)
                    if res is not None:
                        stats["timestamped_comments"] = res.timestamped_comments
                        stats["total_comments"] = res.total_comments
                        curves[name] = normalize(res.curve)
                elif name == "transcript":
                    res = sources[name](video_id, windows)
                    if res is not None:
                        curves[name] = normalize(res)
                else:
                    res = sources[name](video_id, windows, work_dir)
                    if res is not None:
                        curves[name] = normalize(res)
            except Exception as exc:  # one broken signal never sinks the job
                log_event(log, "signal_failed", video_id=video_id, signal=name, error=str(exc)[:200])
                skipped[name] = f"error: {_clean_error(exc)}"
                continue
            if name not in curves:
                skipped[name] = "unavailable for this video"
            # A signal that came back flat carries no information.
            elif max(curves[name], default=0) <= 0:
                curves.pop(name)
                skipped[name] = "no variation (flat signal)"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)  # always clean temp audio/video

    if not curves:
        raise NoDataAvailable(
            "No official heatmap exists and no signal (comments, captions, audio, video) could be analysed."
        )

    weights = renormalize_weights(s.weights, list(curves.keys()))
    segs = combine_signals(windows, curves, s.weights)
    for seg, v in zip(segs, calibrate_shape([x.score for x in segs], s.estimate_median_target)):
        seg.score = v
    signals = [n for n in ["comments", "transcript", "audio", "visual"] if n in curves]
    stats["signals_skipped"] = skipped
    conf, reason = estimate_confidence(signals, stats["timestamped_comments"])
    progress(0.95, "scoring")
    return HeatmapData(
        video_id=video_id,
        title=info.get("title"),
        duration=duration,
        source="estimated",
        confidence=conf,
        confidence_reason=reason,
        signals_used=signals,
        weights={k: round(v, 3) for k, v in weights.items()},
        segments=[asdict(x) for x in segs],
        window=window,
        stats=stats,
    )


def _clean_error(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    msg = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    msg = re.sub(r"https?://\S+", "<url>", msg)  # never leak proxy credentials or signed URLs
    return msg[:200]


def _default_sources() -> dict[str, Callable[..., Any]]:
    from .sources import audio, comments, transcript, visual

    return {
        "comments": comments.comment_signal,
        "transcript": transcript.transcript_signal,
        "audio": audio.audio_signal,
        "visual": visual.visual_signal,
    }


def build_heatmap(
    video_id: str,
    window: float,
    force_estimate: bool = False,
    redis=None,
    progress: ProgressFn | None = None,
    info: dict[str, Any] | None = None,
    fetch_info: Callable[[str], dict[str, Any]] | None = None,
    official_fn: Callable[[str, dict[str, Any] | None], HeatmapData | None] | None = None,
    sources: dict[str, Callable[..., Any]] | None = None,
) -> HeatmapData:
    """Full chain. Typed errors (private, live, blocked...) propagate to the caller."""
    progress = progress or (lambda p, m: None)
    if info is None:
        from .sources.official import fetch_metadata

        progress(0.02, "fetching metadata")
        info = (fetch_info or fetch_metadata)(video_id)
    if not force_estimate:
        progress(0.05, "checking official heatmap")
        data = (official_fn or official_data)(video_id, info)
        if data:
            return data
    return estimated_data(video_id, info, window, redis=redis, progress=progress, sources=sources)


# ------------------------------------------------------------- render ------
def render_result(data: HeatmapData, top: int, bottom: int) -> dict[str, Any]:
    s = get_settings()
    segs = data.segs()
    peaks, drops = select_ranges(segs, top, bottom, s.merge_tolerance)
    estimated = data.source == "estimated"

    def fmt(r) -> dict[str, Any]:
        item: dict[str, Any] = {
            "start": round(r.start, 2),
            "end": round(r.end, 2),
            "start_hms": to_hms(r.start),
            "end_hms": to_hms(r.end),
            "score": round(r.score, 3),
            "type": r.kind,
            "link": timestamp_link(data.video_id, r.start),
        }
        if estimated:
            if r.kind == "peak":
                item["signals"] = contributing_signals(segs, r.indices, data.weights)
            else:  # for drop-offs show every signal's (low) value, weakest first
                names = segs[r.indices[0]].signals.keys()
                avg = {n: sum(segs[i].signals.get(n, 0) for i in r.indices) / len(r.indices) for n in names}
                item["signals"] = [{"name": n, "value": round(v, 3)} for n, v in sorted(avg.items(), key=lambda kv: kv[1])]
        else:
            item["signals"] = ["official_most_replayed"]
        return item

    result: dict[str, Any] = {
        "video_id": data.video_id,
        "title": data.title,
        "duration": data.duration,
        "source": data.source,
        "confidence": data.confidence,
        "confidence_reason": data.confidence_reason,
        "signals_used": data.signals_used,
        **({"signals_skipped": data.stats.get("signals_skipped", {})} if estimated else {}),
        "most_engaging": [fmt(r) for r in peaks],
        "least_engaging": [fmt(r) for r in drops],
        "full_heatmap": [
            {
                "start": round(x.start, 2),
                "end": round(x.end, 2),
                "score": round(x.score, 3),
                **({"signals": {k: round(v, 3) for k, v in x.signals.items()}} if estimated else {}),
            }
            for x in segs
        ],
    }
    if estimated:
        result["is_estimate"] = True
        result["disclaimer"] = estimate_disclaimer(list(data.signals_used))
        result["weights"] = data.weights
        result["window_seconds"] = data.window
    else:
        result["is_estimate"] = False
        result["disclaimer"] = "Scores are YouTube's relative replay intensity (0-1), not raw view counts."
    return result
