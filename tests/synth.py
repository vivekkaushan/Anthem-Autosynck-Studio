"""Synthetic speech-like audio with exactly known offsets, for measuring real sync error."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt


def speechlike(seconds: float, sr: int = 16000, seed: int = 1, pauses: bool = True) -> np.ndarray:
    """Band-limited noise with syllable-rate amplitude modulation and random pauses (non-repeating)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    x = sosfilt(butter(4, [150, 3500], btype="band", fs=sr, output="sos"), rng.standard_normal(n))
    env = np.abs(sosfilt(butter(2, 6, fs=sr, output="sos"), rng.standard_normal(n)))
    env /= env.max()
    x = x * (0.15 + env)
    if pauses:
        gate = np.ones(n)
        t = 0
        while t < n:
            t += int(rng.uniform(2, 6) * sr)
            d = int(rng.uniform(0.3, 1.2) * sr)
            gate[t:t + d] = 0.02
        x = x * gate
    return (x / np.abs(x).max() * 0.5).astype(np.float32)


def cut(x: np.ndarray, sr: int, start_s: float, dur_s: float) -> np.ndarray:
    """Recording that started at master time `start_s` (so true offset = +start_s)."""
    a = int(round(start_s * sr))
    return x[a:a + int(dur_s * sr)]


def pad_start(x: np.ndarray, sr: int, lead_s: float) -> np.ndarray:
    """Recording that started `lead_s` BEFORE the master (true offset = -lead_s); lead is unrelated noise."""
    rng = np.random.default_rng(99)
    lead = (rng.standard_normal(int(lead_s * sr)) * 0.01).astype(np.float32)
    return np.concatenate([lead, x])


def add_noise(x: np.ndarray, snr_db: float, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = float(np.mean(x.astype(np.float64) ** 2))
    n = rng.standard_normal(len(x)) * np.sqrt(p / 10 ** (snr_db / 10))
    return (x + n).astype(np.float32)


def write(path: Path, x: np.ndarray, sr: int) -> Path:
    sf.write(str(path), x, sr, subtype="FLOAT")
    return path
