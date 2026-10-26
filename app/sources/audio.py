"""Signal: audio energy.

Downloads audio only (converted to WAV by ffmpeg, resampled to 16 kHz mono on load), then per window:
  - loudness: mean RMS in dB (librosa)
  - speech rate proxy: onset density
  - bursts: frames that are both loud and noise-like (high spectral flatness),
    a cheap detector for laughter / applause / cheering
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..logging_setup import log_event
from ..urls import canonical_url
from .. import ytdl

log = logging.getLogger(__name__)
SR = 16000
HOP = 512


def download_audio(video_id: str, out_dir: str) -> str:
    return ytdl.download(
        canonical_url(video_id),
        out_dir,
        fmt="bestaudio[abr<=128]/bestaudio/worst",
        postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
    )


def analyse_audio(path: str, windows: list[tuple[float, float]]) -> list[float]:
    import librosa  # lazy, heavy
    import numpy as np

    from ..scoring import normalize

    y, sr = librosa.load(path, sr=SR, mono=True)
    if y.size == 0:
        return [0.0] * len(windows)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    db = librosa.amplitude_to_db(rms, ref=np.max)
    flat = librosa.feature.spectral_flatness(y=y, hop_length=HOP)[0]
    onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=HOP, units="time")
    frame_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)
    loud_thr = np.percentile(db, 75)
    flat_thr = np.percentile(flat, 80)

    loud, rate, burst = [], [], []
    for a, b in windows:
        m = (frame_t >= a) & (frame_t < b)
        if not m.any():
            loud.append(0.0); rate.append(0.0); burst.append(0.0)
            continue
        loud.append(float(db[m].mean()))
        rate.append(float(((onsets >= a) & (onsets < b)).sum()) / max(b - a, 1e-6))
        burst.append(float(((db[m] > loud_thr) & (flat[m] > flat_thr)).mean()))
    L, R, B = normalize(loud), normalize(rate), normalize(burst)
    return [0.5 * l + 0.3 * r + 0.2 * bb for l, r, bb in zip(L, R, B)]


def audio_signal(video_id: str, windows: list[tuple[float, float]], work_dir: str) -> list[float] | None:
    try:
        path = download_audio(video_id, work_dir)
        return analyse_audio(path, windows)
    except Exception as exc:
        log_event(log, "audio_failed", video_id=video_id, error=str(exc)[:200])
        if get_settings().log_level.upper() == "DEBUG":
            log.exception("audio")
        raise  # the pipeline records the reason in signals_skipped
