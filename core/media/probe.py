"""FFprobe integration: inspect media without reading it into memory."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from app.errors import MediaError

log = logging.getLogger(__name__)

_TC_RE = re.compile(r"^(\d{1,2})[:;](\d{2})[:;](\d{2})([:;])(\d{2,3})$")


@dataclass(frozen=True)
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    frame_rate: Fraction        # nominal (r_frame_rate)
    avg_frame_rate: Fraction    # measured average
    time_base: Fraction
    variable_frame_rate: bool


@dataclass(frozen=True)
class AudioStream:
    index: int
    codec: str
    sample_rate: int
    channels: int
    time_base: Fraction


@dataclass
class ProbeResult:
    path: str
    duration: Fraction | None
    video: list[VideoStream] = field(default_factory=list)
    audio: list[AudioStream] = field(default_factory=list)
    timecode: str | None = None
    drop_frame: bool = False
    creation_time: str | None = None   # informational only; never used as a sync reference
    format_name: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio)

    @property
    def primary_video(self) -> VideoStream | None:
        return self.video[0] if self.video else None

    def summary(self) -> dict[str, str]:
        v, a = self.primary_video, (self.audio[0] if self.audio else None)
        return {
            "Duration": f"{float(self.duration):.3f} s" if self.duration is not None else "unknown",
            "Video": (f"{v.width}×{v.height} @ {float(v.frame_rate):.3f} fps ({v.codec})"
                      + (" · VFR" if v.variable_frame_rate else "")) if v else "none",
            "Audio": (f"{a.sample_rate} Hz · {a.channels} ch · stream {a.index} ({a.codec})"
                      + (f" · {len(self.audio)} streams" if len(self.audio) > 1 else "")) if a else "none",
            "Timecode": (self.timecode + (" DF" if self.drop_frame else " NDF")) if self.timecode else "none",
        }


def parse_fraction(text: str | None) -> Fraction | None:
    """Parse '30000/1001' or '25' into an exact Fraction; None for missing/zero-denominator."""
    if not text:
        return None
    try:
        f = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None
    return f


def parse_timecode(tc: str | None) -> tuple[str | None, bool]:
    """Return (normalized timecode, is_drop_frame). Drop-frame is signalled by ';' before frames."""
    if not tc:
        return None, False
    m = _TC_RE.match(tc.strip())
    if not m:
        return None, False
    h, mi, s, sep, fr = m.groups()
    return f"{int(h):02d}:{mi}:{s}{sep}{fr}", sep == ";"


def _find_tc(data: dict) -> str | None:
    for s in data.get("streams", []):
        tc = (s.get("tags") or {}).get("timecode")
        if tc:
            return tc
    return (data.get("format", {}).get("tags") or {}).get("timecode")


def parse_probe_json(path: str, data: dict) -> ProbeResult:
    """Convert raw ffprobe JSON to a ProbeResult. Pure function (unit-tested without ffprobe)."""
    fmt = data.get("format", {})
    warnings: list[str] = []
    dur = parse_fraction(fmt.get("duration"))
    video: list[VideoStream] = []
    audio: list[AudioStream] = []
    for s in data.get("streams", []):
        ctype = s.get("codec_type")
        tb = parse_fraction(s.get("time_base")) or Fraction(0)
        if ctype == "video":
            if s.get("disposition", {}).get("attached_pic"):
                continue  # cover art
            r = parse_fraction(s.get("r_frame_rate")) or Fraction(0)
            avg = parse_fraction(s.get("avg_frame_rate")) or r
            # VFR heuristic: nominal and average rate differ by more than 0.5 %
            vfr = bool(r and avg and abs(r - avg) / r > Fraction(5, 1000))
            if vfr:
                warnings.append(f"Variable frame rate video stream {s.get('index')} (nominal {float(r):.3f}, average {float(avg):.3f} fps)")
            video.append(VideoStream(int(s["index"]), s.get("codec_name", "?"), int(s.get("width", 0)), int(s.get("height", 0)), r, avg, tb, vfr))
        elif ctype == "audio":
            audio.append(AudioStream(int(s["index"]), s.get("codec_name", "?"), int(s.get("sample_rate", 0) or 0), int(s.get("channels", 0) or 0), tb))
    if dur is None:
        durs = [parse_fraction(s.get("duration")) for s in data.get("streams", [])]
        durs = [d for d in durs if d]
        dur = max(durs) if durs else None
    if dur is None:
        warnings.append("Duration unavailable")
    tc, df = parse_timecode(_find_tc(data))
    ct = (fmt.get("tags") or {}).get("creation_time")
    if not video and not audio:
        raise MediaError(f"No audio or video streams found in {Path(path).name}")
    return ProbeResult(path, dur, video, audio, tc, df, ct, fmt.get("format_name", ""), warnings)


def probe_file(path: str, ffprobe: str, timeout: float = 60.0) -> ProbeResult:
    """Run ffprobe on one file. Raises MediaError for missing, unreadable or corrupt media."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"File not found: {path}")
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffprobe timed out on {p.name}") from exc
    except OSError as exc:
        raise MediaError(f"Could not run ffprobe: {exc}") from exc
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed for {p.name}: {proc.stderr.strip()[:300] or 'unknown error'}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise MediaError(f"ffprobe returned invalid JSON for {p.name}") from exc
    result = parse_probe_json(str(p), data)
    if proc.stderr.strip():
        result.warnings.append(proc.stderr.strip()[:200])
    return result
