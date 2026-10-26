from app.scoring import (
    Segment, combine_signals, make_windows, normalize, renormalize_weights, select_ranges, to_hms,
)
from app.sources.comments import density_curve, parse_timestamps


def segs_from(scores, size=10):
    return [Segment(i * size, (i + 1) * size, s) for i, s in enumerate(scores)]


def test_make_windows_last_partial():
    assert make_windows(25, 10) == [(0, 10), (10, 20), (20, 25)]
    assert make_windows(0, 10) == []


def test_normalize():
    assert normalize([2, 4, 6]) == [0.0, 0.5, 1.0]
    assert normalize([3, 3, 3]) == [0.0, 0.0, 0.0]
    assert normalize([]) == []


def test_renormalize_weights_drops_missing():
    w = renormalize_weights({"comments": 0.35, "transcript": 0.25, "audio": 0.25, "visual": 0.15}, ["audio", "visual"])
    assert set(w) == {"audio", "visual"}
    assert abs(sum(w.values()) - 1) < 1e-9
    assert abs(w["audio"] - 0.625) < 1e-9


def test_to_hms():
    assert to_hms(0) == "00:00:00"
    assert to_hms(222) == "00:03:42"
    assert to_hms(3730) == "01:02:10"


def test_merge_adjacent_within_tolerance():
    # windows 2-4 are within 0.05 of the 0.9 seed and should merge into one peak range
    segs = segs_from([0.1, 0.3, 0.88, 0.9, 0.86, 0.4, 0.0, 0.02, 0.5, 0.6])
    peaks, drops = select_ranges(segs, top=1, bottom=1, tol=0.05)
    assert (peaks[0].start, peaks[0].end) == (20, 50)
    assert peaks[0].score == 0.9 and peaks[0].kind == "peak"
    assert (drops[0].start, drops[0].end) == (60, 80)
    assert drops[0].kind == "drop-off"


def test_peaks_and_drops_never_overlap():
    segs = segs_from([0.5] * 6)
    peaks, drops = select_ranges(segs, top=3, bottom=3, tol=0.05)
    used = [i for r in peaks + drops for i in r.indices]
    assert len(used) == len(set(used))
    assert len(peaks) == 1 and peaks[0].indices == list(range(6))
    assert drops == []


def test_top_n_count_and_order():
    segs = segs_from([0.1, 0.9, 0.2, 0.7, 0.3, 0.5, 0.0])
    peaks, drops = select_ranges(segs, top=3, bottom=2, tol=0.0)
    assert [p.score for p in peaks] == [0.9, 0.7, 0.5]
    assert [d.score for d in drops] == [0.0, 0.1]


def test_combine_signals_weighted():
    windows = make_windows(30, 10)
    out = combine_signals(windows, {"a": [0, 1, 0], "b": [0, 0, 1]}, {"a": 0.75, "b": 0.25})
    assert [round(s.score, 3) for s in out] == [0.0, 1.0, 0.333]
    assert out[1].signals == {"a": 1.0, "b": 0.0}


def test_parse_timestamps():
    assert parse_timestamps("best part at 3:42 and 1:02:10!", duration=4000) == [222, 3730]
    assert parse_timestamps("12:30 lol 12:30", duration=1000) == [750]
    assert parse_timestamps("at 9:99 or 99:00", duration=10000) == []
    assert parse_timestamps("10:00", duration=300) == []  # beyond video length
    assert parse_timestamps("version 1.2.3 costs $3.50") == []


def test_density_curve_spreads_mentions():
    windows = make_windows(30, 10)
    curve = density_curve([(15, 1.0)], windows, spread=5)
    assert curve == [0.0, 1.0, 0.0]
    curve = density_curve([(10, 1.0)], windows, spread=5)
    assert curve == [0.5, 0.5, 0.0]


def test_visual_cut_detection_ignores_normal_motion():
    from app.sources.visual import detect_cuts

    diffs = [(i / 2, 3.0 + (i % 3)) for i in range(40)]
    diffs[10] = (5.0, 90.0)
    diffs[30] = (15.0, 70.0)
    assert detect_cuts(diffs) == [5.0, 15.0]


def test_downloads_never_share_a_folder(tmp_path, monkeypatch):
    import sys, types
    from app import ytdl

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def extract_info(self, url, download):
            path = self.opts["outtmpl"].replace("%(id)s", "vid").replace("%(ext)s", self.opts["ext"])
            with open(path, "wb") as f:
                f.write(b"x" * self.opts["size"])

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    monkeypatch.setattr(ytdl, "base_opts", lambda **kw: kw)
    big_audio = ytdl.download("u", str(tmp_path), "a", ext="wav", size=1000)
    small_video = ytdl.download("u", str(tmp_path), "v", ext="mp4", size=10)
    assert big_audio.endswith(".wav") and small_video.endswith(".mp4")
