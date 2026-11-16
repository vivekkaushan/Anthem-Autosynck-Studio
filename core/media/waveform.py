"""Waveform peak data for timeline drawing. Chunked reads; memory stays bounded for long recordings."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from app.errors import Cancelled
from workers.base import CancelToken

PEAKS_PER_SEC = 50


def peaks_path(wav: Path) -> Path:
    return wav.with_suffix(".peaks.npy")


def compute_peaks(wav: Path, token: CancelToken | None = None) -> np.ndarray:
    """Return float32 array (n, 2) of (min, max) per 1/PEAKS_PER_SEC second bucket."""
    with sf.SoundFile(str(wav)) as f:
        hop = max(1, f.samplerate // PEAKS_PER_SEC)
        parts: list[np.ndarray] = []
        for block in f.blocks(blocksize=hop * 4000, dtype="float32"):
            if token is not None and token.cancelled:
                raise Cancelled()
            n = (len(block) // hop) * hop
            if n:
                r = block[:n].reshape(-1, hop)
                parts.append(np.stack([r.min(axis=1), r.max(axis=1)], axis=1))
            if n < len(block):
                tail = block[n:]
                parts.append(np.array([[tail.min(), tail.max()]], dtype=np.float32))
    return np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, 2), np.float32)


def load_or_compute(wav: Path, token: CancelToken | None = None) -> np.ndarray:
    cache = peaks_path(wav)
    if cache.is_file() and cache.stat().st_mtime >= wav.stat().st_mtime:
        try:
            return np.load(cache)
        except (OSError, ValueError):
            cache.unlink(missing_ok=True)
    pk = compute_peaks(wav, token)
    tmp = cache.with_name(cache.stem + ".tmp.npy")
    np.save(tmp, pk)
    tmp.replace(cache)
    return pk
