"""Signal: visual change.

Downloads a low-resolution, video-only stream (<= VISUAL_MAX_HEIGHT) and computes:
  - motion: mean absolute difference of 64x36 grayscale frames sampled at 2 fps
  - cut density: frame jumps far above the video's typical motion, per window
Frames are decoded by ffmpeg, so every codec YouTube serves (AV1, VP9, H.264) works.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

from ..config import get_settings
from ..logging_setup import log_event
from ..urls import canonical_url
from .. import ytdl

log = logging.getLogger(__name__)


def download_video(video_id: str, out_dir: str) -> str:
    h = get_settings().visual_max_height
    return ytdl.download(
        canonical_url(video_id),
        out_dir,
        fmt=f"bv*[height<={h}][vcodec^=avc1]/bv*[height<={h}][vcodec!=none]/wv*/worst",  # small stream; ffmpeg decodes any codec
    )


FRAME_W, FRAME_H = 64, 36


def frame_diffs(path: str, sample_fps: float = 2.0) -> list[tuple[float, float]]:
    """Decode with ffmpeg (handles AV1/VP9/H.264 alike) into tiny grayscale frames at
    `sample_fps`, and return (time, mean absolute difference vs previous frame)."""
    import numpy as np

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    cmd = [
        ffmpeg, "-v", "error", "-nostdin", "-i", path, "-an",
        "-vf", f"fps={sample_fps},scale={FRAME_W}:{FRAME_H},format=gray",
        "-f", "rawvideo", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=get_settings().job_timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore')[-200:]}")
    size = FRAME_W * FRAME_H
    n = len(proc.stdout) // size
    if n < 2:
        raise RuntimeError("video decoded to fewer than 2 frames")
    frames = np.frombuffer(proc.stdout[: n * size], dtype=np.uint8).reshape(n, size).astype(np.float32)
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=1)
    return [((i + 1) / sample_fps, float(d)) for i, d in enumerate(diffs)]


def detect_cuts(diffs: list[tuple[float, float]]) -> list[float]:
    """A cut is a frame-to-frame jump far above the video's typical motion."""
    import numpy as np

    if not diffs:
        return []
    d = np.array([v for _, v in diffs])
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med))) or 1.0
    thr = max(25.0, med + 6.0 * mad)
    return [t for t, v in diffs if v >= thr]


def analyse_video(path: str, windows: list[tuple[float, float]]) -> list[float]:
    from ..scoring import normalize

    diffs = frame_diffs(path)
    cuts = detect_cuts(diffs)
    cut_counts, mot = [], []
    for a, b in windows:
        cut_counts.append(sum(1 for t in cuts if a <= t < b) / max(b - a, 1e-6))
        vals = [v for t, v in diffs if a <= t < b]
        mot.append(sum(vals) / len(vals) if vals else 0.0)
    C, M = normalize(cut_counts), normalize(mot)
    return [0.6 * c + 0.4 * m for c, m in zip(C, M)]


def visual_signal(video_id: str, windows: list[tuple[float, float]], work_dir: str) -> list[float] | None:
    try:
        path = download_video(video_id, work_dir)
        return analyse_video(path, windows)
    except Exception as exc:
        log_event(log, "visual_failed", video_id=video_id, error=str(exc)[:200])
        raise  # the pipeline records the reason in signals_skipped
