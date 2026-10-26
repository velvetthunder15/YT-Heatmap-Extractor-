"""Pure scoring utilities: windows, normalisation, weighted combination, peak/drop-off
selection with range merging, and HH:MM:SS formatting. No I/O, fully unit-tested."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class Segment:
    start: float
    end: float
    score: float  # 0..1
    signals: dict[str, float] = field(default_factory=dict)  # per-signal normalised values


# ---------------------------------------------------------------- windows ---
def make_windows(duration: float, window: float) -> list[tuple[float, float]]:
    """Split [0, duration) into consecutive windows; the last one may be shorter."""
    if duration <= 0 or window <= 0:
        return []
    n = int(math.ceil(duration / window))
    return [(i * window, min((i + 1) * window, duration)) for i in range(n)]


def normalize(values: Sequence[float]) -> list[float]:
    """Min-max normalise to 0..1. A flat (or empty) series becomes all zeros."""
    vals = [0.0 if (v is None or math.isnan(v)) else float(v) for v in values]
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return [0.0] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]


def renormalize_weights(weights: dict[str, float], available: Sequence[str]) -> dict[str, float]:
    """Keep only available signals and rescale their weights to sum to 1."""
    kept = {k: max(0.0, weights.get(k, 0.0)) for k in available}
    total = sum(kept.values())
    if total <= 0:
        return {k: 1.0 / len(kept) for k in kept} if kept else {}
    return {k: v / total for k, v in kept.items()}


def combine_signals(
    windows: list[tuple[float, float]],
    signals: dict[str, list[float]],
    weights: dict[str, float],
) -> list[Segment]:
    """Weighted sum of already-normalised per-window signal curves."""
    w = renormalize_weights(weights, list(signals.keys()))
    segs: list[Segment] = []
    for i, (a, b) in enumerate(windows):
        per = {name: float(curve[i]) if i < len(curve) else 0.0 for name, curve in signals.items()}
        score = sum(w[name] * per[name] for name in per)
        segs.append(Segment(a, b, score, per))
    # Rescale combined score to 0..1 so it is comparable across videos.
    scaled = normalize([s.score for s in segs])
    for s, v in zip(segs, scaled):
        s.score = v
    return segs


# ------------------------------------------------------------ formatting ---
def to_hms(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ------------------------------------------------------------- selection ---
@dataclass
class Range:
    start: float
    end: float
    score: float
    kind: str  # "peak" | "drop-off"
    indices: list[int]


def _grow(segs: list[Segment], seed: int, used: set[int], tol: float) -> list[int]:
    """Grow a range from seed over adjacent unused segments whose score is within tol of the seed."""
    base = segs[seed].score
    lo = hi = seed
    while lo - 1 >= 0 and (lo - 1) not in used and abs(segs[lo - 1].score - base) <= tol:
        lo -= 1
    while hi + 1 < len(segs) and (hi + 1) not in used and abs(segs[hi + 1].score - base) <= tol:
        hi += 1
    return list(range(lo, hi + 1))


def select_ranges(segs: list[Segment], top: int, bottom: int, tol: float = 0.05) -> tuple[list[Range], list[Range]]:
    """Pick the top-N peaks and bottom-N drop-offs. Each seed segment is merged with
    neighbours whose score is within `tol`, and peaks/drop-offs never overlap."""
    used: set[int] = set()
    peaks: list[Range] = []
    for i in sorted(range(len(segs)), key=lambda k: (-segs[k].score, k)):
        if len(peaks) >= top:
            break
        if i in used:
            continue
        idx = _grow(segs, i, used, tol)
        used.update(idx)
        peaks.append(Range(segs[idx[0]].start, segs[idx[-1]].end, segs[i].score, "peak", idx))

    drops: list[Range] = []
    for i in sorted(range(len(segs)), key=lambda k: (segs[k].score, k)):
        if len(drops) >= bottom:
            break
        if i in used:
            continue
        idx = _grow(segs, i, used, tol)
        used.update(idx)
        drops.append(Range(segs[idx[0]].start, segs[idx[-1]].end, segs[i].score, "drop-off", idx))
    return peaks, drops


def contributing_signals(segs: list[Segment], idx: list[int], weights: dict[str, float], min_share: float = 0.2) -> list[dict]:
    """Signals that explain a range: weighted contribution >= min_share of the total."""
    if not idx or not segs[idx[0]].signals:
        return []
    names = list(segs[idx[0]].signals.keys())
    w = renormalize_weights(weights, names)
    avg = {n: sum(segs[i].signals.get(n, 0.0) for i in idx) / len(idx) for n in names}
    contrib = {n: w[n] * avg[n] for n in names}
    total = sum(contrib.values()) or 1.0
    out = [
        {"name": n, "value": round(avg[n], 3), "share": round(c / total, 3)}
        for n, c in sorted(contrib.items(), key=lambda kv: -kv[1])
        if c / total >= min_share
    ]
    return out
