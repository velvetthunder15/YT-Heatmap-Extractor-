"""Signal: transcript analysis.

Captions come from youtube-transcript-api, falling back to yt-dlp's caption tracks
(json3). Each window is scored with keyword rules: topic shifts, questions, emphasis
words, hook phrases, claim density and speech density. An optional LLM pass
(OpenAI-compatible, LLM_API_KEY) is blended in when configured.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..config import get_settings
from ..logging_setup import log_event
from ..urls import canonical_url

log = logging.getLogger(__name__)

EMPHASIS = {
    "amazing", "incredible", "insane", "crazy", "huge", "massive", "important", "never", "always",
    "best", "worst", "literally", "actually", "seriously", "wow", "secret", "mistake", "shocking",
    "finally", "biggest", "critical", "key", "must", "warning", "unbelievable",
}
HOOKS = [
    "here's the thing", "the secret", "watch this", "wait for it", "you won't believe", "let me show you",
    "the trick is", "most people", "the reason", "here's why", "pay attention", "this is where",
    "the problem is", "the truth is", "what happened next", "spoiler", "let's go", "check this out",
    "number one", "the best part", "plot twist", "game changer",
]
STOP = set("the a an and or but if then so to of in on at for with is are was were be been it this that i you we they he she my your our".split())
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|x|k|million|billion|dollars?)?\b", re.I)
WORD_RE = re.compile(r"[a-z']+")


@dataclass
class Cue:
    start: float
    duration: float
    text: str


# ----------------------------------------------------------- fetching -------
def _from_transcript_api(video_id: str) -> list[Cue] | None:
    from youtube_transcript_api import YouTubeTranscriptApi  # lazy

    s = get_settings()
    langs = ["en", "en-US", "en-GB"]
    try:  # youtube-transcript-api >= 1.0
        kwargs = {}
        if s.yt_proxy:
            from youtube_transcript_api.proxies import GenericProxyConfig

            kwargs["proxy_config"] = GenericProxyConfig(http_url=s.yt_proxy, https_url=s.yt_proxy)
        api = YouTubeTranscriptApi(**kwargs)
        listing = api.list(video_id)
        try:
            tr = listing.find_transcript(langs)
        except Exception:
            tr = next(iter(listing))  # any language; rules still pick up questions/numbers/shifts
        return [Cue(sn.start, sn.duration, sn.text) for sn in tr.fetch()]
    except TypeError:  # legacy < 1.0 API
        data = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
        return [Cue(d["start"], d["duration"], d["text"]) for d in data]


def _from_ytdlp(video_id: str) -> list[Cue] | None:
    import httpx

    from .. import ytdl

    s = get_settings()
    info = ytdl.extract_info(canonical_url(video_id))
    tracks = {**(info.get("automatic_captions") or {}), **(info.get("subtitles") or {})}
    lang = next((l for l in ("en", "en-US", "en-GB", "en-orig") if l in tracks), next(iter(tracks), None))
    if not lang:
        return None
    url = next((t["url"] for t in tracks[lang] if t.get("ext") == "json3"), None)
    if not url:
        return None
    with httpx.Client(proxy=s.yt_proxy or None, timeout=20) as c:
        data = c.get(url).json()
    cues: list[Cue] = []
    for ev in data.get("events", []):
        text = "".join(seg.get("utf8", "") for seg in ev.get("segs", []) or []).strip()
        if text:
            cues.append(Cue(ev.get("tStartMs", 0) / 1000, ev.get("dDurationMs", 0) / 1000, text))
    return cues


def fetch_transcript(video_id: str) -> list[Cue] | None:
    for fn in (_from_transcript_api, _from_ytdlp):
        try:
            cues = fn(video_id)
            if cues:
                return cues
        except Exception as exc:
            log_event(log, "transcript_source_failed", video_id=video_id, source=fn.__name__, error=str(exc)[:200])
    return None


# ------------------------------------------------------------ scoring -------
def window_texts(cues: list[Cue], windows: list[tuple[float, float]]) -> list[str]:
    texts = [""] * len(windows)
    if not windows:
        return texts
    size = windows[0][1] - windows[0][0]
    for c in cues:
        i = min(int(c.start // size), len(windows) - 1)
        texts[i] += " " + c.text.replace("\n", " ")
    return [t.strip() for t in texts]


def score_texts(texts: list[str]) -> list[float]:
    """Keyword-rule score per window (raw, not normalised)."""
    scores: list[float] = []
    prev: set[str] = set()
    for t in texts:
        low = t.lower()
        words = WORD_RE.findall(low)
        content = {w for w in words if w not in STOP and len(w) > 2}
        if not words:
            scores.append(0.0)
            prev = content
            continue
        shift = 1 - (len(content & prev) / len(content | prev)) if (content | prev) and prev else 0.0
        questions = low.count("?") + sum(low.count(q) for q in (" why ", " how ", " what if "))
        emphasis = sum(1 for w in words if w in EMPHASIS)
        hooks = sum(1 for h in HOOKS if h in low)
        claims = len(NUMBER_RE.findall(low))
        density = min(len(words) / 30.0, 1.5)  # ~3 words/s in a 10s window
        scores.append(0.25 * shift + 0.15 * questions + 0.15 * emphasis + 0.35 * hooks + 0.10 * claims + 0.2 * density)
        prev = content
    return scores


def llm_scores(texts: list[str]) -> list[float] | None:
    """Optional: ask an LLM to rate each window 0-10 for viewer interest."""
    s = get_settings()
    if not s.llm_api_key:
        return None
    import httpx

    out: list[float] = []
    batch = 40
    try:
        with httpx.Client(timeout=60) as c:
            for i in range(0, len(texts), batch):
                chunk = texts[i : i + batch]
                prompt = (
                    "Rate how engaging each transcript window is for a typical viewer (0=boring, 10=gripping). "
                    "Return only a JSON array of numbers, one per window, same order.\n"
                    + json.dumps([t[:400] for t in chunk])
                )
                r = c.post(
                    f"{s.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {s.llm_api_key}"},
                    json={"model": s.llm_model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]},
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                arr = json.loads(content[content.index("[") : content.rindex("]") + 1])
                if len(arr) != len(chunk):
                    return None
                out.extend(float(x) for x in arr)
    except Exception as exc:
        log_event(log, "llm_pass_failed", error=str(exc)[:200])
        return None
    return out


def transcript_signal(video_id: str, windows: list[tuple[float, float]]) -> list[float] | None:
    from ..scoring import normalize

    cues = fetch_transcript(video_id)
    if not cues:
        return None
    texts = window_texts(cues, windows)
    if sum(1 for t in texts if t) < max(3, len(texts) // 10):
        return None  # too sparse to say anything
    rules = normalize(score_texts(texts))
    llm = llm_scores(texts)
    if llm:
        b = get_settings().llm_blend
        llm_n = normalize(llm)
        return [(1 - b) * r + b * l for r, l in zip(rules, llm_n)]
    return rules
