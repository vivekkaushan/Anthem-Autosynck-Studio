"""Generate synthetic test media with FFmpeg (no sample files are checked in)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def run(*args: str) -> None:
    subprocess.run([FFMPEG, "-y", "-v", "error", *args], check=True)


def make_wav(path: Path, seconds=2.0, rate=48000, channels=1, freq=440) -> Path:
    run("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate={rate}:duration={seconds}", "-ac", str(channels), str(path))
    return path


def make_video(path: Path, seconds=2.0, fps="30000/1001", size="320x180", audio=True, timecode: str | None = None) -> Path:
    args = ["-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=44100:duration={seconds}"]
    args += ["-c:v", "mpeg4", "-q:v", "5"]
    if audio:
        args += ["-c:a", "aac"]
    if timecode:
        args += ["-timecode", timecode]
    run(*args, str(path))
    return path


def make_video_with_audio_file(path: Path, wav: Path, seconds: float, audio_rate: int = 44100) -> Path:
    """Video whose soundtrack is an existing wav (AAC, resampled), to test real extraction."""
    run("-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={seconds}", "-i", str(wav),
        "-map", "0:v", "-map", "1:a", "-c:v", "mpeg4", "-q:v", "6", "-c:a", "aac", "-ar", str(audio_rate), "-shortest", str(path))
    return path
