"""End-to-end: real FFmpeg extraction + correlation, error measured against known offsets."""
import numpy as np
import pytest

from app.dependencies import find_binary
from core.synchronization.engine import SyncInput, synchronize
from tests import media_factory as mf, synth
from workers.base import CancelToken

FFMPEG, FFPROBE = find_binary("ffmpeg"), find_binary("ffprobe")
pytestmark = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg not available")
SR = 16000
TOL = 0.002   # allows for AAC encoder delay; still ~1/20 of a video frame


def test_multi_camera_multi_audio_different_rates(tmp_path):
    from core.media.probe import probe_file
    master = synth.speechlike(240, SR, seed=11)
    mpath = synth.write(tmp_path / "master.wav", np.repeat(master, 3), 48000)   # 48 kHz recorder (3x oversampled)
    truth = {"cam1": 5.0, "cam2": 61.5, "lav": 20.25}
    cam1 = mf.make_video_with_audio_file(tmp_path / "c1.mp4", synth.write(tmp_path / "a1.wav", synth.cut(master, SR, 5.0, 100), SR), 100, 44100)
    cam2 = mf.make_video_with_audio_file(tmp_path / "c2.mp4", synth.write(tmp_path / "a2.wav", synth.add_noise(synth.cut(master, SR, 61.5, 90) * 0.3, 3), SR), 90, 48000)
    lav = synth.write(tmp_path / "lav.wav", synth.cut(master, SR, 20.25, 150), SR)
    silent_vid = mf.make_video(tmp_path / "noaudio.mp4", audio=False)
    files = {"master": mpath, "cam1": cam1, "cam2": cam2, "lav": lav, "mute": silent_vid}
    inputs = []
    for k, p in files.items():
        info = probe_file(str(p), FFPROBE)
        inputs.append(SyncInput(k, k, str(p), info.audio[0].index if info.audio else None))
    prog = []
    res = synchronize(inputs, "master", FFMPEG, tmp_path / "cache", lambda p, m: prog.append(p), CancelToken())
    for k, off in truth.items():
        err = abs(res[k].offset - off)
        print(f"{k}: true={off} measured={res[k].offset:.5f} err={err*1000:.3f} ms conf={res[k].confidence}")
        assert err < TOL and res[k].confidence in ("High", "Medium"), (k, res[k])
    assert res["master"].method == "reference" and res["master"].offset == 0
    assert res["mute"].confidence == "Failed" and "No audio" in res["mute"].notes[0]   # handled, not crashed
    assert prog[-1] == 100


def test_cache_reused_and_silent_file_reported(tmp_path):
    master = synth.speechlike(60, SR, seed=2)
    m = synth.write(tmp_path / "m.wav", master, SR)
    quiet = synth.write(tmp_path / "q.wav", np.zeros(30 * SR, dtype=np.float32), SR)
    c = synth.write(tmp_path / "c.wav", synth.cut(master, SR, 10, 40), SR)
    ins = [SyncInput("m", "m", str(m), 0), SyncInput("q", "q", str(quiet), 0), SyncInput("c", "c", str(c), 0)]
    cache = tmp_path / "cache"
    r1 = synchronize(ins, "m", FFMPEG, cache, lambda p, s: None, CancelToken())
    n_cached = len(list(cache.glob("*.wav")))
    r2 = synchronize(ins, "m", FFMPEG, cache, lambda p, s: None, CancelToken())
    assert len(list(cache.glob("*.wav"))) == n_cached and not list(cache.glob("*.part.wav"))   # reused, no leftovers
    assert r1["q"].confidence == "Failed" and "silent" in r1["q"].notes[0].lower()
    assert abs(r1["c"].offset - 10) < TOL and r2["c"].offset == r1["c"].offset


def test_corrupt_file_reported_not_fatal(tmp_path):
    master = synth.speechlike(60, SR, seed=2)
    m = synth.write(tmp_path / "m.wav", master, SR)
    bad = tmp_path / "bad.mp4"; bad.write_bytes(b"\x00garbage" * 200)
    res = synchronize([SyncInput("m", "m", str(m), 0), SyncInput("b", "b", str(bad), 0)], "m", FFMPEG,
                      tmp_path / "cache", lambda p, s: None, CancelToken())
    assert res["b"].confidence == "Failed" and not list((tmp_path / "cache").glob("*.part.wav"))


def test_fallback_camera_to_camera(tmp_path):
    """cam B shares no audio with the master but overlaps cam A, which does: chained offset is found."""
    master = synth.speechlike(200, SR, seed=21)
    ambient = synth.speechlike(200, SR, seed=22)            # what only the cameras hear
    cam_a = synth.cut(master, SR, 0, 100) + 0 * ambient[:100 * SR]
    cam_a_full = cam_a * 0.6 + synth.cut(ambient, SR, 30, 100) * 0.6   # A: master voice + ambient, starts at master 0 / ambient 30
    cam_b = synth.cut(ambient, SR, 50, 70)                              # B: ambient only, starts ambient 50
    m = synth.write(tmp_path / "m.wav", master, SR)
    a = synth.write(tmp_path / "a.wav", cam_a_full, SR)
    b = synth.write(tmp_path / "b.wav", cam_b, SR)
    # B is at ambient 50 = A time 20 (A starts at ambient 30) = master time 20  -> offset +20
    res = synchronize([SyncInput("m", "m", str(m), 0), SyncInput("a", "a", str(a), 0), SyncInput("b", "b", str(b), 0)],
                      "m", FFMPEG, tmp_path / "cache", lambda p, s: None, CancelToken())
    assert abs(res["a"].offset - 0.0) < TOL
    assert "via a" in res["b"].method and abs(res["b"].offset - 20.0) < TOL, res["b"]
    assert res["b"].confidence != "High"      # chained results never claim High


def test_analyze_button_end_to_end(qapp, tmp_path, monkeypatch):
    """Import a folder tree, probe, press Analyze & Sync, read the results table."""
    from PySide6.QtCore import QEventLoop, QTimer
    from app.config import Config
    from app.dependencies import check_dependencies
    import ui.main_window as mw
    monkeypatch.setattr(mw, "cache_dir", lambda: tmp_path / "appcache")
    master = synth.speechlike(120, SR, seed=31)
    root = tmp_path / "Shoot"
    (root / "Camera 1").mkdir(parents=True); (root / "Camera 2").mkdir(); (root / "Audio 1").mkdir()
    mf.make_video_with_audio_file(root / "Camera 1" / "a.mp4", synth.write(tmp_path / "t1.wav", synth.cut(master, SR, 3.0, 50), SR), 50)
    mf.make_video_with_audio_file(root / "Camera 1" / "b.mp4", synth.write(tmp_path / "t2.wav", synth.cut(master, SR, 70.0, 40), SR), 40)
    mf.make_video_with_audio_file(root / "Camera 2" / "c.mp4", synth.write(tmp_path / "t3.wav", synth.cut(master, SR, 25.5, 60), SR), 60)
    synth.write(root / "Audio 1" / "rec.wav", master, SR)

    w = mw.MainWindow(Config(), check_dependencies())
    assert not w.a_sync.isEnabled()
    added, _, groups = w.state.add_folder(str(root))
    w.probe(added)

    def wait(cond, ms=20000):
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit)
        t = QTimer(); t.timeout.connect(lambda: loop.quit() if cond() else None); t.start(50)
        loop.exec(); t.stop()
    wait(lambda: all(m.info or m.error for m in added))
    master_item = next(m for m in added if m.session == "Audio 1")
    w.state.set_master(master_item.id)
    assert w.a_sync.isEnabled()
    w.a_sync.trigger()
    assert w.a_cancel.isEnabled() and not w.a_sync.isEnabled()
    wait(lambda: w._sync_job is None and w.state.sync_results)
    res = w.state.sync_results
    expect = {"a.mp4": 3.0, "b.mp4": 70.0, "c.mp4": 25.5}
    for m in added:
        if m.name in expect:
            assert abs(res[m.id].offset - expect[m.name]) < 0.002 and res[m.id].usable, (m.name, res[m.id])
    assert w.inspector.results.rowCount() == 4
    assert w.inspector.results.item(0, 2).text() in ("High", "Medium")
    assert not w.a_cancel.isEnabled() and w.a_sync.isEnabled()
    for j in list(w._jobs): j.wait()
