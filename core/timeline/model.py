"""Rational-time timeline: clips placed on a common project timeline.

Source time (time inside a recording) and timeline time (position on the project timeline) are kept
separate. Positions are exact fractions of a second (sample-exact at the 16 kHz analysis rate), so no
floating-point error accumulates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from core.media.models import MediaItem, MediaKind

OFFSET_RATE = 16000    # offsets are rounded to the analysis sample grid


def to_rational(seconds: float, rate: int = OFFSET_RATE) -> Fraction:
    return Fraction(round(seconds * rate), rate)


@dataclass
class Clip:
    media_id: str
    name: str
    start: Fraction          # timeline position of source_in
    duration: Fraction
    source_in: Fraction = Fraction(0)
    synced: bool = True
    confidence: str = ""     # High | Medium | Low | Failed | Reference | Not analyzed
    offset: Fraction = Fraction(0)   # master_time = source_time + offset (before timeline shift)

    @property
    def end(self) -> Fraction:
        return self.start + self.duration


@dataclass
class Track:
    label: str               # V1, V2, A1 ...
    title: str               # CAM 01 / Master Audio
    kind: str                # "V" | "A"
    role: str
    clips: list[Clip] = field(default_factory=list)


@dataclass
class Timeline:
    tracks: list[Track]
    origin: Fraction = Fraction(0)      # master time that sits at timeline 0 (<= 0 if a recording starts before master)

    @property
    def duration(self) -> Fraction:
        return max((c.end for t in self.tracks for c in t.clips), default=Fraction(0))

    def clip_for(self, media_id: str) -> Clip | None:
        return next((c for t in self.tracks for c in t.clips if c.media_id == media_id), None)

    @property
    def counts(self) -> tuple[int, int]:
        """(synchronized, total) over non-reference clips."""
        cl = [c for t in self.tracks for c in t.clips if c.confidence != "Reference"]
        return sum(1 for c in cl if c.synced), len(cl)


def build_timeline(media: list[MediaItem], results: dict) -> Timeline:
    """Place every probed clip using its sync result (`results`: media id -> SyncResult).

    Un-synchronized clips are placed at the start and flagged `synced=False`; they never get a guessed position.
    """
    def info_duration(m: MediaItem) -> Fraction | None:
        d = getattr(m.info, "duration", None)
        return Fraction(d) if d is not None else None

    clips: list[tuple[MediaItem, Clip]] = []
    for m in media:
        dur = info_duration(m)
        if dur is None:
            continue
        r = results.get(m.id)
        if m.is_master:
            c = Clip(m.id, m.name, Fraction(0), dur, confidence="Reference")
        elif r is not None and r.usable:
            off = to_rational(r.offset)
            c = Clip(m.id, m.name, off, dur, confidence=r.confidence, offset=off)
        else:
            c = Clip(m.id, m.name, Fraction(0), dur, synced=False, confidence=(r.confidence if r else "Not analyzed"))
        clips.append((m, c))
    # shift so the earliest clip starts at 0
    origin = min([Fraction(0)] + [c.start for _, c in clips if c.synced])
    for _, c in clips:
        if c.synced:
            c.start -= origin
    video_roles = sorted({m.role for m, _ in clips if m.kind is MediaKind.VIDEO})
    master_roles = [m.role for m, _ in clips if m.is_master and m.kind is MediaKind.AUDIO]
    audio_roles = master_roles[:1] + sorted({m.role for m, _ in clips if m.kind is MediaKind.AUDIO} - set(master_roles[:1]))
    tracks: list[Track] = []
    for i, role in enumerate(video_roles, 1):
        tracks.append(Track(f"V{i}", role, "V", role))
    for i, role in enumerate(audio_roles, 1):
        title = "Master Audio" if master_roles and role == master_roles[0] else role
        tracks.append(Track(f"A{i}", title, "A", role))
    by_key = {(t.kind, t.role): t for t in tracks}
    for m, c in clips:
        by_key[("V" if m.kind is MediaKind.VIDEO else "A", m.role)].clips.append(c)
    for t in tracks:
        t.clips.sort(key=lambda c: (c.start, c.name))
    return Timeline(tracks, origin)
