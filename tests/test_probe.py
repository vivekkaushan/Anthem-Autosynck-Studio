from fractions import Fraction

import pytest

from app.dependencies import find_binary
from app.errors import MediaError
from core.media.probe import parse_probe_json, parse_timecode, probe_file
from tests import media_factory as mf

FFPROBE = find_binary("ffprobe")
pytestmark = pytest.mark.skipif(not FFPROBE, reason="ffprobe not available")


def test_probe_wav(tmp_path):
    r = probe_file(str(mf.make_wav(tmp_path / "a.wav", 2.0, 48000, 2)), FFPROBE)
    assert r.audio[0].sample_rate == 48000 and r.audio[0].channels == 2 and not r.video
    assert abs(float(r.duration) - 2.0) < 0.05


def test_probe_video_ntsc_timecode_dropframe(tmp_path):
    r = probe_file(str(mf.make_video(tmp_path / "v.mov", fps="30000/1001", timecode="01:02:03;04")), FFPROBE)
    v = r.primary_video
    assert (v.width, v.height) == (320, 180)
    assert v.frame_rate == Fraction(30000, 1001)          # exact rational, not 29.97 float
    assert r.timecode == "01:02:03;04" and r.drop_frame
    assert r.has_audio and r.audio[0].sample_rate == 44100


def test_probe_non_dropframe_timecode(tmp_path):
    r = probe_file(str(mf.make_video(tmp_path / "v.mov", fps="25", timecode="10:00:00:00")), FFPROBE)
    assert r.timecode == "10:00:00:00" and not r.drop_frame and r.primary_video.frame_rate == 25


def test_video_without_audio(tmp_path):
    r = probe_file(str(mf.make_video(tmp_path / "v.mp4", audio=False)), FFPROBE)
    assert not r.has_audio and r.primary_video is not None


def test_missing_file(tmp_path):
    with pytest.raises(MediaError, match="not found"):
        probe_file(str(tmp_path / "nope.mp4"), FFPROBE)


def test_corrupt_and_empty_files(tmp_path):
    bad = tmp_path / "bad.mp4"; bad.write_bytes(b"\x00\x01garbage" * 100)
    empty = tmp_path / "empty.wav"; empty.write_bytes(b"")
    for f in (bad, empty):
        with pytest.raises(MediaError):
            probe_file(str(f), FFPROBE)


def test_vfr_detection_and_missing_duration_pure():
    data = {"format": {}, "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
         "r_frame_rate": "60/1", "avg_frame_rate": "5000/101", "time_base": "1/90000", "duration": "12.5"}]}
    r = parse_probe_json("x.mp4", data)
    assert r.primary_video.variable_frame_rate and r.duration == Fraction(25, 2)
    assert any("Variable frame rate" in w for w in r.warnings)


def test_no_streams_is_error():
    with pytest.raises(MediaError):
        parse_probe_json("x", {"format": {}, "streams": []})


def test_timecode_parsing():
    assert parse_timecode("1:02:03;04") == ("01:02:03;04", True)
    assert parse_timecode("01:00:00:00") == ("01:00:00:00", False)
    assert parse_timecode("garbage") == (None, False)
    assert parse_timecode(None) == (None, False)


def test_probe_job_batch_with_failure(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop
    from workers.probe_worker import make_probe_job
    good = str(mf.make_wav(tmp_path / "g.wav"))
    job = make_probe_job([("1", good), ("2", str(tmp_path / "missing.wav"))], FFPROBE)
    got = {}
    loop = QEventLoop()
    job.finished.connect(lambda r: got.update(r))
    job.done.connect(loop.quit)
    job.start(); loop.exec(); job.wait()
    assert got["1"].has_audio and isinstance(got["2"], MediaError)


def test_main_window_probes_imported_media(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer
    from app.config import Config
    from app.dependencies import check_dependencies
    from ui.main_window import MainWindow
    w = MainWindow(Config(), check_dependencies())
    vid = str(mf.make_video(tmp_path / "c.mov", timecode="01:00:00:00", fps="25"))
    gone = tmp_path / "gone.wav"; gone.write_bytes(b"RIFF")   # corrupt
    added, _ = w.state.add_files([vid, str(gone)])
    w.probe(added)
    loop = QEventLoop(); QTimer.singleShot(8000, loop.quit)
    w.state.changed.connect(lambda: loop.quit() if all(m.info or m.error for m in added) else None)
    loop.exec()
    assert added[0].info is not None and added[0].info.timecode == "01:00:00:00"
    assert added[1].error and added[1].info is None
    w.library.tree.topLevelItem(0).child(0).setSelected(True)
    assert "25.000 fps" in w.inspector.fields["Video"].text()
    for j in list(w._jobs): j.wait()
