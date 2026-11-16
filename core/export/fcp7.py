"""Export a synchronized timeline as legacy Final Cut Pro 7 XML (XMEML v4), which Premiere Pro imports.

Layout: V1..Vn = camera tracks (one per camera role), A1.. = master/recorder audio tracks (one mono track per
channel). When the project has no separate audio recorder (camera-only), each camera's own audio is placed on
audio tracks under its video so the footage keeps its sound.

Times are whole frames at the sequence rate (XMEML cannot store sub-frame positions), so placements are rounded to
the nearest frame (at most half a frame, 10 ms at 50 fps). Clips that were not synchronized are never exported.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from urllib.parse import quote

from core.media.models import MediaItem, MediaKind
from core.timeline.model import Timeline

NTSC_RATES = {Fraction(24000, 1001): 24, Fraction(30000, 1001): 30, Fraction(60000, 1001): 60}


class ExportError(Exception):
    pass


def _rate(parent: ET.Element, fps: Fraction) -> None:
    r = ET.SubElement(parent, "rate")
    ntsc = fps in NTSC_RATES
    ET.SubElement(r, "timebase").text = str(NTSC_RATES[fps] if ntsc else round(float(fps)))
    ET.SubElement(r, "ntsc").text = "TRUE" if ntsc else "FALSE"


def _txt(parent: ET.Element, tag: str, value) -> ET.Element:
    e = ET.SubElement(parent, tag)
    e.text = str(value)
    return e


def _timecode_frames(tc: str | None, base: int) -> int:
    if not tc:
        return 0
    parts = tc.replace(";", ":").split(":")
    try:
        h, m, s, f = (int(x) for x in parts)
    except ValueError:
        return 0
    return ((h * 3600 + m * 60 + s) * base) + f


def _pathurl(path: str) -> str:
    return "file://localhost" + quote(path if path.startswith("/") else "/" + path.replace("\\", "/"), safe="/:")


def sequence_rate(media: list[MediaItem]) -> Fraction:
    for m in media:
        v = getattr(m.info, "primary_video", None)
        if v is not None:
            return Fraction(v.frame_rate)
    return Fraction(25)


def export_xmeml(timeline: Timeline, media: list[MediaItem], name: str = "Anthem Auto Synck Sequence") -> tuple[str, list[str]]:
    """Return (xml text, names of clips left out because they were not synchronized)."""
    by_id = {m.id: m for m in media}
    fps = sequence_rate(media)
    base = round(float(fps))

    def frames(sec) -> int:
        return int(round(Fraction(sec) * fps))

    skipped: list[str] = []
    placed = []     # (track, clip, media)
    for t in timeline.tracks:
        for c in t.clips:
            m = by_id.get(c.media_id)
            if m is None:
                continue
            if not c.synced:
                skipped.append(c.name)
                continue
            placed.append((t, c, m))
    if not placed:
        raise ExportError("No synchronized clips to export. Run Synchronize first.")

    root = ET.Element("xmeml", version="4")
    seq = ET.SubElement(root, "sequence", id="sequence-1")
    _txt(seq, "name", name)
    end_frame = max(frames(c.end) for _, c, _ in placed)
    _txt(seq, "duration", end_frame)
    _rate(seq, fps)
    tc = ET.SubElement(seq, "timecode")
    _rate(tc, fps)
    _txt(tc, "string", "00:00:00:00")
    _txt(tc, "frame", 0)
    _txt(tc, "displayformat", "NDF")
    med = ET.SubElement(seq, "media")

    first_v = next((m.info.primary_video for _, _, m in placed if getattr(m.info, "primary_video", None)), None)
    video = ET.SubElement(med, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    _rate(sc, fps)
    _txt(sc, "width", first_v.width if first_v else 1920)
    _txt(sc, "height", first_v.height if first_v else 1080)
    _txt(sc, "pixelaspectratio", "square")
    audio = ET.SubElement(med, "audio")
    _txt(audio, "numOutputChannels", 2)
    af = ET.SubElement(audio, "format")
    asc = ET.SubElement(af, "samplecharacteristics")
    _txt(asc, "depth", 16)
    _txt(asc, "samplerate", 48000)

    files_written: set[str] = set()

    def file_el(parent: ET.Element, m: MediaItem) -> None:
        fid = f"file-{m.id[:8]}"
        f = ET.SubElement(parent, "file", id=fid)
        if fid in files_written:
            return
        files_written.add(fid)
        info = m.info
        _txt(f, "name", m.name if "." in m.name else m.name)
        _txt(f, "pathurl", _pathurl(m.path))
        _rate(f, fps)
        _txt(f, "duration", frames(info.duration) if getattr(info, "duration", None) else 0)
        ftc = ET.SubElement(f, "timecode")
        _rate(ftc, fps)
        _txt(ftc, "string", getattr(info, "timecode", None) or "00:00:00:00")
        _txt(ftc, "frame", _timecode_frames(getattr(info, "timecode", None), base))
        _txt(ftc, "displayformat", "DF" if getattr(info, "drop_frame", False) else "NDF")
        fm = ET.SubElement(f, "media")
        v = getattr(info, "primary_video", None)
        if v is not None:
            fv = ET.SubElement(fm, "video")
            s = ET.SubElement(fv, "samplecharacteristics")
            _rate(s, Fraction(v.frame_rate))
            _txt(s, "width", v.width)
            _txt(s, "height", v.height)
        if getattr(info, "audio", None):
            a0 = info.audio[0]
            fa = ET.SubElement(fm, "audio")
            s = ET.SubElement(fa, "samplecharacteristics")
            _txt(s, "depth", 16)
            _txt(s, "samplerate", a0.sample_rate)
            _txt(fa, "channelcount", a0.channels)

    counter = [0]

    def clip_el(track_el: ET.Element, c, m: MediaItem, kind: str, channel: int = 1) -> None:
        counter[0] += 1
        ci = ET.SubElement(track_el, "clipitem", id=f"clipitem-{counter[0]}")
        _txt(ci, "name", c.name)
        _txt(ci, "enabled", "TRUE")
        dur = frames(c.duration)
        _txt(ci, "duration", frames(m.info.duration) if getattr(m.info, "duration", None) else dur)
        _rate(ci, fps)
        start = frames(c.start)
        _txt(ci, "start", start)
        _txt(ci, "end", start + dur)
        _txt(ci, "in", frames(c.source_in))
        _txt(ci, "out", frames(c.source_in) + dur)
        file_el(ci, m)
        if kind == "audio":
            st = ET.SubElement(ci, "sourcetrack")
            _txt(st, "mediatype", "audio")
            _txt(st, "trackindex", channel)

    # video tracks: one per camera role
    for t in timeline.tracks:
        if t.kind != "V":
            continue
        te = ET.SubElement(video, "track")
        for tr, c, m in sorted((x for x in placed if x[0] is t), key=lambda x: x[1].start):
            clip_el(te, c, m, "video")

    # audio tracks: recorder/master first; camera-only projects use each camera's own audio
    audio_sources = [t for t in timeline.tracks if t.kind == "A"]
    if not audio_sources:
        audio_sources = [t for t in timeline.tracks if t.kind == "V"]
    for t in audio_sources:
        items = sorted((x for x in placed if x[0] is t and getattr(x[2].info, "audio", None)), key=lambda x: x[1].start)
        if not items:
            continue
        channels = max(x[2].info.audio[0].channels for x in items)
        for ch in range(1, min(2, channels) + 1):
            te = ET.SubElement(audio, "track")
            for tr, c, m in items:
                if m.info.audio[0].channels >= ch:
                    clip_el(te, c, m, "audio", ch)

    ET.indent(root)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode")
    return xml, skipped
