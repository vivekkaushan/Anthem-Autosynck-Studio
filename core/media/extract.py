"""FFmpeg audio extraction into cached mono float32 analysis files. Never touches originals."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from app.errors import Cancelled, MediaError
from workers.base import CancelToken

log = logging.getLogger(__name__)
ANALYSIS_RATE = 16000
CACHE_VERSION = "v1"
SILENCE_RMS = 1e-4


@dataclass(frozen=True)
class AnalysisAudio:
    path: Path
    duration: float       # seconds
    sample_rate: int
    peak_rms: float       # loudest 1 s block RMS
    silent: bool


def cache_key(src: str, stream_index: int, rate: int) -> str:
    st = os.stat(src)
    raw = f"{os.path.abspath(src)}|{st.st_size}|{st.st_mtime_ns}|{stream_index}|{rate}|{CACHE_VERSION}"
    return hashlib.sha1(raw.encode()).hexdigest()


def measure(path: Path, block_s: float = 1.0) -> AnalysisAudio:
    """Chunked loudness scan; bounded memory."""
    peak = 0.0
    with sf.SoundFile(str(path)) as f:
        sr, n = f.samplerate, f.frames
        block = int(sr * block_s)
        while True:
            x = f.read(block, dtype="float32")
            if len(x) == 0:
                break
            peak = max(peak, float(np.sqrt(np.mean(x.astype(np.float64) ** 2))))
    return AnalysisAudio(path, n / sr, sr, peak, peak < SILENCE_RMS)


def extract_analysis_audio(src: str, stream_index: int, ffmpeg: str, cache_dir: Path,
                           rate: int = ANALYSIS_RATE, token: CancelToken | None = None) -> AnalysisAudio:
    """Decode one audio stream to mono float32 WAV at `rate`. Cached; partial files never left behind."""
    if not Path(src).is_file():
        raise MediaError(f"File not found: {src}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{cache_key(src, stream_index, rate)}.wav"
    if out.is_file():
        try:
            return measure(out)
        except (sf.LibsndfileError, RuntimeError):
            log.warning("Cached analysis file %s unreadable; re-extracting", out)
            out.unlink(missing_ok=True)
    tmp = out.with_suffix(".part.wav")
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin", "-i", src, "-map", f"0:{stream_index}", "-vn",
           "-ac", "1", "-ar", str(rate), "-c:a", "pcm_f32le", "-f", "wav", str(tmp)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        while proc.poll() is None:
            if token is not None and token.cancelled:
                proc.kill()
                proc.wait()
                raise Cancelled()
            time.sleep(0.05)
        err = (proc.stderr.read() if proc.stderr else "").strip()
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 100:
            raise MediaError(f"Audio extraction failed for {Path(src).name}: {err[:300] or 'no audio decoded'}")
        tmp.replace(out)
    finally:
        if proc.stderr:
            proc.stderr.close()
        tmp.unlink(missing_ok=True)   # cleanup on failure / cancel
    audio = measure(out)
    if audio.duration <= 0:
        out.unlink(missing_ok=True)
        raise MediaError(f"No audio samples decoded from {Path(src).name}")
    return audio


def analysis_wav_path(src: str, stream_index: int, cache_dir: Path, rate: int = ANALYSIS_RATE) -> Path:
    """Where the cached analysis file for this source/stream lives (may not exist yet)."""
    return cache_dir / f"{cache_key(src, stream_index, rate)}.wav"
