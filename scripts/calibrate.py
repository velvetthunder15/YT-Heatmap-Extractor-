"""Tune the estimate against YouTube's own "Most replayed" data.

Pick videos that HAVE official data (ideally 10+, similar to the ones you analyse). For each,
this runs the official fetch and a forced estimate, compares them, then searches for the signal
weights and score shape that make estimates match the official curves best.

    python -m scripts.calibrate VIDEO [VIDEO ...]          # URLs or IDs
    python -m scripts.calibrate --file videos.txt          # one per line
    python -m scripts.calibrate ... --apply                # also write the best settings to .env

Runs on the computer that hosts the server (cloud IPs get blocked by YouTube). An estimate takes
a minute or two per video. Results are cached in calibration/ so re-runs are instant.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "calibration"
SIGNALS = ["comments", "transcript", "audio", "visual"]


# ------------------------------------------------------------------ maths --
def ranks(xs):
    order = sorted(range(len(xs)), key=xs.__getitem__)
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def spearman(a, b):
    return pearson(ranks(a), ranks(b))


def resample(segs, windows):
    """Overlap-weighted average of official segments onto the estimate's windows."""
    out = []
    for a, b in windows:
        tot = wsum = 0.0
        for s in segs:
            ov = min(b, s["end"]) - max(a, s["start"])
            if ov > 0:
                tot += ov * s["score"]
                wsum += ov
        out.append(tot / wsum if wsum else 0.0)
    return out


def top_hits(est, off, k=5, slack=1):
    """How many of the official top-k segments have an estimate top-k segment within `slack` windows."""
    te = sorted(range(len(est)), key=lambda i: -est[i])[:k]
    to = sorted(range(len(off)), key=lambda i: -off[i])[:k]
    return sum(any(abs(i - j) <= slack for j in te) for i in to) / max(1, len(to))


def combine(sig_rows, weights):
    from app.scoring import normalize, renormalize_weights

    names = [n for n in SIGNALS if n in sig_rows[0]] if sig_rows else []
    w = renormalize_weights(weights, names)
    return normalize([sum(w[n] * row.get(n, 0.0) for n in names) for row in sig_rows])


# ------------------------------------------------------------------- data --
def video_id(s: str) -> str:
    from app.urls import extract_video_id

    return extract_video_id(s.strip())


def collect(vid: str, window: int) -> dict | None:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{vid}-{window}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    from app.pipeline import build_heatmap
    from app.sources.official import fetch_metadata

    print(f"  {vid}: fetching...", flush=True)
    info = fetch_metadata(vid)
    off = build_heatmap(vid, window, info=info)
    if off.source != "official":
        print(f"  {vid}: no official 'Most replayed' data, skipped")
        return None
    est = build_heatmap(vid, window, force_estimate=True, info=info,
                        progress=lambda p, m: print(f"\r  {vid}: {m:<24}", end="", flush=True))
    print()
    rec = {
        "video_id": vid,
        "title": info.get("title"),
        "official": off.segments,
        "estimate": [{"start": s["start"], "end": s["end"], "signals": s["signals"]} for s in est.segments],
    }
    f.write_text(json.dumps(rec), encoding="utf-8")
    return rec


# ------------------------------------------------------------------- main --
def score_set(data, weights):
    sp, hits = [], []
    for d in data:
        windows = [(s["start"], s["end"]) for s in d["estimate"]]
        off = resample(d["official"], windows)
        est = combine([s["signals"] for s in d["estimate"]], weights)
        sp.append(spearman(est, off))
        hits.append(top_hits(est, off))
    return sum(sp) / len(sp), sum(hits) / len(hits), sp, hits


def best_median(data):
    """The median score official curves actually have, so estimates can be shaped to match."""
    meds = []
    for d in data:
        vals = sorted(s["score"] for s in d["official"])
        meds.append(vals[len(vals) // 2])
    meds.sort()
    return round(max(0.02, meds[len(meds) // 2]), 3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--apply", action="store_true", help="write the best settings to .env")
    a = ap.parse_args()

    from app.config import get_settings

    items = list(a.videos)
    if a.file:
        items += [l for l in Path(a.file).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    if not items:
        ap.error("give some videos that have YouTube's 'Most replayed' graph")

    data = []
    for it in items:
        try:
            rec = collect(video_id(it), a.window)
        except Exception as exc:  # noqa: BLE001  one bad video shouldn't stop the run
            print(f"  {it}: failed ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        if rec:
            data.append(rec)
    if not data:
        sys.exit("No usable videos (each needs official data and a working estimate).")

    s = get_settings()
    cur = s.weights
    c_sp, c_hit, sps, hits = score_set(data, cur)
    print(f"\nCurrent weights {cur}")
    for d, sp, h in zip(data, sps, hits):
        print(f"  {d['video_id']}  rank match {sp:+.2f}  top-5 found {h:.0%}  {(d.get('title') or '')[:50]}")
    print(f"  average: rank match {c_sp:+.2f}, top-5 found {c_hit:.0%}")

    # Grid search on the simplex in steps of 0.05; objective favours finding the real peaks.
    best = (c_hit * 0.6 + c_sp * 0.4, cur)
    steps = [i / 20 for i in range(21)]
    for wc, wt, wa in itertools.product(steps, steps, steps):
        wv = round(1 - wc - wt - wa, 2)
        if wv < 0:
            continue
        w = {"comments": wc, "transcript": wt, "audio": wa, "visual": wv}
        sp, hit, _, _ = score_set(data, w)
        obj = hit * 0.6 + sp * 0.4
        if obj > best[0] + 1e-9:
            best = (obj, w)
    w = best[1]
    b_sp, b_hit, _, _ = score_set(data, w)
    med = best_median(data)
    print(f"\nBest weights {w}")
    print(f"  average: rank match {b_sp:+.2f}, top-5 found {b_hit:.0%}  (was {c_sp:+.2f}, {c_hit:.0%})")
    print(f"  official curves have a median score of {med}, so ESTIMATE_MEDIAN_TARGET={med}")
    if len(data) < 8:
        print("  Note: with fewer than ~8 videos these weights may just fit those videos. Add more.")

    lines = {f"WEIGHT_{k.upper()}": f"{v:.2f}" for k, v in w.items()}
    lines["ESTIMATE_MEDIAN_TARGET"] = str(med)
    if a.apply:
        env = ROOT / ".env"
        text = env.read_text(encoding="utf-8")
        for k, v in lines.items():
            pat = re.compile(rf"^{k}=.*$", re.M)
            text = pat.sub(f"{k}={v}", text) if pat.search(text) else text.rstrip("\n") + f"\n{k}={v}\n"
        env.write_text(text, encoding="utf-8")
        print("\nSaved to .env. Restart the server to use them.")
    else:
        print("\nTo use them, re-run with --apply, or add to .env:")
        for k, v in lines.items():
            print(f"  {k}={v}")


if __name__ == "__main__":
    main()
