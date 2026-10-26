"""Signal: visual change.

Downloads a low-resolution, video-only stream (<= VISUAL_MAX_HEIGHT) and computes:
  - cut density: scene cuts per window (PySceneDetect ContentDetector)
  - motion: mean absolute frame difference of downscaled grayscale frames sampled at ~2 fps
"""
from __future__ import annotations

import logging

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
        fmt=f"bv*[height<={h}][vcodec^=avc1]/bv*[height<={h}][vcodec!=none]/wv*/worst",  # prefer H.264: OpenCV decodes it everywhere
    )


def scene_cuts(path: str) -> list[float]:
    from scenedetect import ContentDetector, detect  # lazy

    scenes = detect(path, ContentDetector(threshold=27.0))
    return [start.get_seconds() for start, _ in scenes[1:]]


def motion_series(path: str, sample_fps: float = 2.0) -> list[tuple[float, float]]:
    import cv2  # lazy (installed with scenedetect[opencv-headless])
    import numpy as np

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / sample_fps)))
    out: list[tuple[float, float]] = []
    prev = None
    idx = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                g = cv2.cvtColor(cv2.resize(frame, (64, 36)), cv2.COLOR_BGR2GRAY).astype("float32")
                if prev is not None:
                    out.append((idx / fps, float(np.abs(g - prev).mean())))
                prev = g
            idx += 1
    finally:
        cap.release()
    return out


def analyse_video(path: str, windows: list[tuple[float, float]]) -> list[float]:
    from ..scoring import normalize

    cuts = scene_cuts(path)
    motion = motion_series(path)
    cut_counts, mot = [], []
    for a, b in windows:
        cut_counts.append(sum(1 for t in cuts if a <= t < b) / max(b - a, 1e-6))
        vals = [v for t, v in motion if a <= t < b]
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
