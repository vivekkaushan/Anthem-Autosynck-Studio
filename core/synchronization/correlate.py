"""Waveform cross-correlation between two analysis files.

Convention: the returned offset satisfies  reference_time = target_time + offset.
A window of the target is normalised-cross-correlated against the whole reference (chunked FFT, bounded
memory). Several windows spread across the target must agree on a straight line (offset vs. time) for a
result to be trusted; the slope of that line is the clock drift.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfiltfilt

from app.errors import Cancelled, SyncError
from workers.base import CancelToken

log = logging.getLogger(__name__)

AGREE_TOL_S = 0.003          # windows must agree within 3 ms of the fitted line
MIN_PSR = 1.15               # peak / second-peak; below this the match is ambiguous (silence, loops)
MIN_NCC = 0.08               # minimum normalised correlation to accept a window
GUARD_S = 0.5                # exclusion zone around the peak when looking for the runner-up
MAX_DRIFT_PPM = 1000.0
CHUNK_S = 240.0


@dataclass
class WindowMatch:
    target_start: float      # seconds into target where the window begins
    offset: float            # reference_time - target_time at this window
    ncc: float
    psr: float


@dataclass
class PairResult:
    ok: bool
    offset: float = 0.0              # at target t = 0
    drift_ppm: float = 0.0           # target clock speed error relative to reference
    correlation: float = 0.0         # median NCC of verified windows
    psr: float = 0.0
    match_duration: float = 0.0      # seconds of target audio verified
    windows_verified: int = 0
    windows_total: int = 0
    confidence: str = "Failed"       # High | Medium | Low | Failed
    notes: list[str] = field(default_factory=list)
    matches: list[WindowMatch] = field(default_factory=list)


def _sos(sr: int):
    return butter(4, [100 / (sr / 2), min(4000, sr / 2 * 0.9) / (sr / 2)], btype="band", output="sos")


def preprocess(x: np.ndarray, sr: int) -> np.ndarray:
    """DC removal + band-pass (100 Hz – 4 kHz). Zero-phase so it does not shift timing."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < 256:
        return x - x.mean() if len(x) else x
    x = x - x.mean()
    return sosfiltfilt(_sos(sr), x)


def _read(f: sf.SoundFile, start: int, n: int) -> np.ndarray:
    f.seek(max(0, start))
    return f.read(n, dtype="float32", always_2d=False)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def _search(window: np.ndarray, ref: sf.SoundFile, sr: int, token: CancelToken | None) -> tuple[float, float, float]:
    """Best normalised cross-correlation of `window` against the entire reference file.

    Returns (position_seconds_in_reference, ncc, peak_to_second_peak_ratio).
    """
    L = len(window)
    w = window - window.mean()
    wn2 = float(np.dot(w, w))
    if wn2 <= 0:
        return 0.0, 0.0, 0.0
    guard = int(GUARD_S * sr)
    chunk = int(CHUNK_S * sr)
    total = ref.frames
    if total < L:
        return 0.0, 0.0, 0.0
    records: list[tuple[int, float]] = []
    best = (-1.0, 0, 0.0)  # value, global index, fractional
    start = 0
    while start + L <= total:
        if token is not None and token.cancelled:
            raise Cancelled()
        m = preprocess(_read(ref, start, chunk + L - 1), sr)
        if len(m) < L:
            break
        corr = fftconvolve(m, w[::-1], mode="valid")
        cs = np.concatenate(([0.0], np.cumsum(m * m)))
        energy = cs[L:] - cs[:-L]
        ok = energy / L > 1e-8
        ncc = np.zeros_like(corr)
        ncc[ok] = corr[ok] / np.sqrt(energy[ok] * wn2)
        i = int(np.argmax(ncc))
        v = float(ncc[i])
        records.append((start + i, v))
        lo, hi = max(0, i - guard), min(len(ncc), i + guard + 1)
        for a, b in ((0, lo), (hi, len(ncc))):       # runner-up outside the exclusion zone
            if b > a:
                j = a + int(np.argmax(ncc[a:b]))
                records.append((start + j, float(ncc[j])))
        if v > best[0]:
            frac = 0.0
            if 0 < i < len(ncc) - 1:
                y0, y1, y2 = ncc[i - 1], ncc[i], ncc[i + 1]
                d = y0 - 2 * y1 + y2
                if d != 0:
                    frac = float(np.clip(0.5 * (y0 - y2) / d, -1, 1))   # sub-sample parabolic interpolation
            best = (v, start + i, frac)
        start += chunk
    if best[0] <= 0:
        return 0.0, 0.0, 0.0
    second = max([val for idx, val in records if abs(idx - best[1]) > guard] or [1e-9])
    psr = best[0] / max(second, 1e-9)
    return (best[1] + best[2]) / sr, best[0], psr


def pick_windows(tgt: sf.SoundFile, sr: int, win: int, n: int) -> list[int]:
    """Evenly spread window starts (samples), skipping near-silent places."""
    total = tgt.frames
    cands = np.unique(np.linspace(0, total - win, 2 * n).astype(int))
    loud = []
    for s in cands:
        r = _rms(preprocess(_read(tgt, int(s), win), sr))
        if r > 1e-4:
            loud.append((int(s), r))
    if not loud:
        return []
    rs = np.array([r for _, r in loud])
    keep = [s for s, r in loud if r >= 0.1 * np.percentile(rs, 80)]
    if len(keep) > n:
        keep = [keep[int(k)] for k in np.linspace(0, len(keep) - 1, n)]
    return keep


def _fit_line(ms: list[WindowMatch]) -> tuple[float, float, list[int]]:
    """Largest consistent set under offset = a + b*t. Zero-drift lines win ties."""
    t = np.array([m.target_start for m in ms])
    o = np.array([m.offset for m in ms])
    lines: list[tuple[float, float]] = [(float(oi), 0.0) for oi in o]
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            if abs(t[j] - t[i]) >= 1.0:
                b = (o[j] - o[i]) / (t[j] - t[i])
                if abs(b) * 1e6 <= MAX_DRIFT_PPM:
                    lines.append((float(o[i] - b * t[i]), float(b)))
    best_in: list[int] = []
    for a, b in lines:          # zero-drift candidates come first, so ties never invent drift
        inl = [k for k in range(len(ms)) if abs(o[k] - (a + b * t[k])) <= AGREE_TOL_S]
        if len(inl) > len(best_in):
            best_in = inl
    if len(best_in) >= 3 and np.ptp(t[best_in]) >= 30.0:
        b, a = np.polyfit(t[best_in], o[best_in], 1)
    else:
        a, b = float(np.median(o[best_in])), 0.0
    return float(a), float(b), best_in


def classify(verified: int, total: int, ncc: float, psr: float) -> str:
    if verified >= 3 and verified >= 0.5 * total and (ncc >= 0.15 or psr >= 4.0):
        return "High"
    if verified >= 2 or (verified == 1 and ncc >= 0.5 and psr >= 2.0):
        return "Medium"
    return "Low"


def correlate_pair(ref_wav: Path, tgt_wav: Path, *, n_windows: int = 10, win_s: float = 20.0,
                   token: CancelToken | None = None,
                   progress: Callable[[int, str], None] | None = None) -> PairResult:
    """Locate `tgt_wav` on the reference timeline. Never raises for 'no match'; returns confidence Failed/Low."""
    with sf.SoundFile(str(ref_wav)) as ref, sf.SoundFile(str(tgt_wav)) as tgt:
        sr = ref.samplerate
        if tgt.samplerate != sr:
            raise SyncError("Analysis files must share one sample rate")
        dur_t, dur_r = tgt.frames / sr, ref.frames / sr
        win_len = min(win_s, dur_t, dur_r)
        if win_len < 2.0:
            return PairResult(False, notes=[f"Recordings too short to correlate ({win_len:.1f} s window)"])
        win = int(win_len * sr)
        starts = pick_windows(tgt, sr, win, n_windows)
        if not starts:
            return PairResult(False, notes=["Target audio is silent; nothing to correlate"])
        matches: list[WindowMatch] = []
        rejected_ambiguous = 0
        for k, s in enumerate(starts):
            if token is not None and token.cancelled:
                raise Cancelled()
            if progress:
                progress(int(100 * k / len(starts)), f"Correlating window {k + 1}/{len(starts)}")
            w = preprocess(_read(tgt, s, win), sr)
            pos, ncc, psr = _search(w, ref, sr, token)
            if ncc < MIN_NCC:
                continue
            if psr < MIN_PSR:
                rejected_ambiguous += 1
                continue
            matches.append(WindowMatch(s / sr, pos - s / sr, ncc, psr))
    notes: list[str] = []
    if rejected_ambiguous:
        notes.append(f"{rejected_ambiguous} window(s) rejected as ambiguous (repetitive or featureless audio)")
    if not matches:
        notes.append("No window correlated with the reference")
        return PairResult(False, windows_total=len(starts), confidence="Failed", notes=notes)
    a, b, inl = _fit_line(matches)
    ver = [matches[k] for k in inl]
    ncc = float(np.median([m.ncc for m in ver]))
    psr = float(np.median([m.psr for m in ver]))
    conf = classify(len(ver), len(starts), ncc, psr)
    drift = b * 1e6
    if abs(drift) >= 5 and len(ver) >= 3:
        notes.append(f"Clock drift detected: {drift:+.1f} ppm (not corrected; source media untouched)")
    if len(ver) < len(matches):
        notes.append(f"{len(matches) - len(ver)} window(s) disagreed with the consensus and were ignored")
    return PairResult(True, a, drift if len(ver) >= 3 else 0.0, ncc, psr, len(ver) * win_len,
                      len(ver), len(starts), conf, notes, matches)
