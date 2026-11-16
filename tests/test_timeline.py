from fractions import Fraction
from types import SimpleNamespace

import numpy as np

from core.media.models import MediaItem, MediaKind
from core.media.waveform import PEAKS_PER_SEC, compute_peaks, load_or_compute
from core.synchronization.engine import SyncResult
from core.timeline.model import build_timeline, to_rational
from tests import synth


def item(name, kind, role, dur, master=False):
    m = MediaItem(path=f"/x/{name}", kind=kind, role=role, name=name, is_master=master)
    m.info = SimpleNamespace(duration=Fraction(dur))
    return m


def res(m, off, conf="High"):
    return SyncResult(m.id, "ref", "waveform", offset=off, confidence=conf)


def test_positions_and_rational_precision():
    master = item("rec.wav", MediaKind.AUDIO, "AUDIO 01", 600, master=True)
    c1 = item("a.mp4", MediaKind.VIDEO, "CAM 01", 100)
    c2 = item("b.mp4", MediaKind.VIDEO, "CAM 01", 80)        # second clip of the same camera
    c3 = item("c.mp4", MediaKind.VIDEO, "CAM 02", 90)
    tl = build_timeline([master, c1, c2, c3], {c1.id: res(c1, 12.3456), c2.id: res(c2, 250.0), c3.id: res(c3, 33.3333333)})
    assert [t.label for t in tl.tracks] == ["V1", "V2", "A1"]
    v1 = tl.tracks[0]
    assert [c.name for c in v1.clips] == ["a.mp4", "b.mp4"]                  # both clips on ONE camera track
    assert v1.clips[0].start == Fraction(round(12.3456 * 16000), 16000)
    assert tl.tracks[2].title == "Master Audio" and tl.tracks[2].clips[0].start == 0
    assert tl.duration == Fraction(600)
    assert tl.counts == (3, 3)
    # exact fractions: no float drift when adding durations
    assert v1.clips[0].end - v1.clips[0].start == 100


def test_negative_offset_shifts_origin():
    master = item("rec.wav", MediaKind.AUDIO, "AUDIO 01", 300, master=True)
    cam = item("a.mp4", MediaKind.VIDEO, "CAM 01", 100)
    tl = build_timeline([master, cam], {cam.id: res(cam, -7.25)})
    assert tl.origin == Fraction(-29, 4)
    assert tl.clip_for(cam.id).start == 0 and tl.clip_for(master.id).start == Fraction(29, 4)   # master moved right by 7.25 s
    assert tl.clip_for(cam.id).offset == Fraction(-29, 4)         # source/offset kept separately from timeline position


def test_unsynced_clips_are_flagged_not_guessed():
    master = item("rec.wav", MediaKind.AUDIO, "AUDIO 01", 300, master=True)
    good = item("g.mp4", MediaKind.VIDEO, "CAM 01", 50)
    low = item("l.mp4", MediaKind.VIDEO, "CAM 02", 50)
    never = item("n.mp4", MediaKind.VIDEO, "CAM 03", 50)
    tl = build_timeline([master, good, low, never], {good.id: res(good, 5), low.id: res(low, 99, "Low")})
    assert tl.clip_for(low.id).synced is False and tl.clip_for(low.id).start == 0   # Low, unconfirmed: not placed at 99
    assert tl.clip_for(never.id).confidence == "Not analyzed"
    assert tl.counts == (1, 3)
    low_res = res(low, 99, "Low"); low_res.confirmed = True                        # user confirmed -> placed
    tl2 = build_timeline([master, good, low, never], {good.id: res(good, 5), low.id: low_res})
    assert tl2.clip_for(low.id).synced and tl2.clip_for(low.id).start == 99


def test_peaks_match_known_signal(tmp_path):
    sr = 16000
    x = np.zeros(3 * sr, dtype=np.float32)
    x[sr:2 * sr] = 0.5 * np.sin(2 * np.pi * 200 * np.arange(sr) / sr)       # loud second 1..2 only
    w = synth.write(tmp_path / "a.wav", x, sr)
    pk = compute_peaks(w)
    assert pk.shape == (3 * PEAKS_PER_SEC, 2)
    assert np.abs(pk[:PEAKS_PER_SEC]).max() == 0 and np.abs(pk[2 * PEAKS_PER_SEC:]).max() == 0
    assert 0.45 < pk[PEAKS_PER_SEC:2 * PEAKS_PER_SEC, 1].max() <= 0.5 and pk[PEAKS_PER_SEC:2 * PEAKS_PER_SEC, 0].min() < -0.45
    pk2 = load_or_compute(w); pk3 = load_or_compute(w)                         # computed, then served from cache
    assert (tmp_path / "a.peaks.npy").exists() and np.array_equal(pk2, pk3) and np.array_equal(pk, pk2)


def test_peaks_cancel(tmp_path):
    import pytest
    from app.errors import Cancelled
    from workers.base import CancelToken
    w = synth.write(tmp_path / "a.wav", synth.speechlike(30, 16000), 16000)
    t = CancelToken(); t.cancel()
    with pytest.raises(Cancelled):
        compute_peaks(w, t)


def test_view_zoom_scroll_and_hit_testing(qapp):
    from app.state import ProjectState
    from ui.timeline_view import TimelineView, HEADER_W, RULER_H, LANE_H
    s = ProjectState()
    master = item("rec.wav", MediaKind.AUDIO, "AUDIO 01", 300, master=True)
    cam = item("a.mp4", MediaKind.VIDEO, "CAM 01", 100)
    s.media = [master, cam]
    s.sync_results = {cam.id: res(cam, 50.0)}
    s.rebuild_timeline()
    v = TimelineView(s); v.resize(1000, 400)
    v.fit()
    assert abs(v.px_per_sec - (1000 - HEADER_W - 20) / 300) < 1e-9
    t_before = v._t(500)
    v.zoom(2.0, 500)
    assert abs(v._t(500) - t_before) < 1e-6                                # zoom keeps the point under the cursor fixed
    picked = []
    v.clip_selected.connect(picked.append)
    v.px_per_sec, v.scroll = 5.0, 0.0
    from PySide6.QtCore import QPointF, Qt, QEvent
    from PySide6.QtGui import QMouseEvent
    x = v._x(75.0); y = RULER_H + 5                                       # lane V1 at t=75 s (cam spans 50..150)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(x, y), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    v.mousePressEvent(ev)
    assert picked == [cam.id] and v.selected == cam.id
    v.grab()                                                               # paints without error


def test_waveform_is_actually_drawn(qapp):
    """Regression: the min/max reduction used to raise at the clip end and silently draw nothing."""
    from fractions import Fraction
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from app.state import ProjectState
    from ui.timeline_view import TimelineView

    class C:
        start = Fraction(0)
        source_in = Fraction(0)

    view = TimelineView(ProjectState())
    view.resize(900, 300)
    view.px_per_sec = 10
    peaks = np.tile(np.array([[-0.2, 0.2]], dtype=np.float32), (1500, 1))      # 30 s, constant amplitude
    img = QImage(900, 300, QImage.Format_ARGB32)
    base = QColor("#1a627f")
    img.fill(base)
    p = QPainter(img)
    view._draw_wave(p, peaks, C, QRectF(210, 60, 290, 31), QColor("#8beaff"))   # covers the whole 30 s (300 px) incl. last column
    p.end()
    arr = np.frombuffer(img.bits(), np.uint8).reshape(300, 900, 4)
    drawn = (arr != np.array([base.blue(), base.green(), base.red(), 255])).any(axis=2)
    assert drawn[:, 210:500].sum() > 300          # many columns got a line
    assert drawn[:, 495:500].any()                # including the very last columns
