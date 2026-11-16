from fractions import Fraction
import xml.etree.ElementTree as ET

from core.export.fcp7 import ExportError, export_xmeml
from core.media.models import MediaItem, MediaKind
from core.media.probe import AudioStream, ProbeResult, VideoStream
from core.synchronization.engine import SyncResult
from core.timeline.model import build_timeline
import pytest


def _vid(path, role, dur, tc=None):
    info = ProbeResult(path, Fraction(dur), [VideoStream(0, "h264", 1920, 1080, Fraction(50), Fraction(50), Fraction(1, 50), False)],
                       [AudioStream(1, "pcm", 48000, 2, Fraction(1, 48000))], tc)
    return MediaItem(path, MediaKind.VIDEO, role, info=info)


def test_xml_positions_and_skips():
    a, b, c = _vid("/Volumes/x y/a.mp4", "CAM 01", 100), _vid("/Volumes/x y/b.mp4", "CAM 02", 60, "10:00:00:10"), _vid("/v/c.mp4", "CAM 02", 30)
    a.is_master = True
    res = {a.id: SyncResult(a.id, a.id, "reference", confidence="High"),
           b.id: SyncResult(b.id, a.id, "waveform", offset=12.34, confidence="High"),
           c.id: SyncResult(c.id, a.id, "waveform", confidence="Failed")}
    tl = build_timeline([a, b, c], res)
    xml, skipped = export_xmeml(tl, [a, b, c])
    assert skipped == ["c.mp4"]
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])
    seq = root.find("sequence")
    assert seq.find("rate/timebase").text == "50" and seq.find("duration").text == "5000"
    tracks = seq.findall("media/video/track")
    assert len(tracks) == 2
    cb = tracks[1].find("clipitem")
    assert cb.find("start").text == str(round(12.34 * 50)) and cb.find("end").text == str(round(12.34 * 50) + 3000)
    assert cb.find("file/pathurl").text == "file://localhost/Volumes/x%20y/b.mp4"
    assert len(seq.findall("media/audio/track")) == 4        # camera-only: 2 cameras x stereo


def test_nothing_synced_raises():
    a = _vid("/v/a.mp4", "CAM 01", 10)
    tl = build_timeline([a], {})
    with pytest.raises(ExportError):
        export_xmeml(tl, [a])
