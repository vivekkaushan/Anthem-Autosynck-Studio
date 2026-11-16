"""Multi-recording synchronization against one master audio reference."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.errors import Cancelled, MediaError
from core.media.extract import ANALYSIS_RATE, AnalysisAudio, extract_analysis_audio
from core.synchronization.correlate import PairResult, correlate_pair
from workers.base import CancelToken

log = logging.getLogger(__name__)
_RANK = {"Failed": 0, "Low": 1, "Medium": 2, "High": 3}


@dataclass
class SyncInput:
    id: str
    name: str
    path: str
    stream_index: int | None     # None = file has no audio stream
    hint: float | None = None    # approximate wall-clock seconds (e.g. creation time); only orders candidates, never sets offsets


@dataclass
class SyncResult:
    media_id: str
    reference_id: str            # media the offset is measured against (master, or a secondary reference)
    method: str                  # "reference" | "waveform" | "waveform via <name>"
    offset: float = 0.0          # seconds: master_time = source_time + offset
    correlation: float = 0.0
    match_duration: float = 0.0
    windows_verified: int = 0
    windows_total: int = 0
    drift_ppm: float = 0.0
    confidence: str = "Failed"   # High | Medium | Low | Failed
    confirmed: bool = False      # user accepted a low-confidence result
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.confidence in ("High", "Medium") or (self.confidence == "Low" and self.confirmed)


def _from_pair(mid: str, ref: str, method: str, r: PairResult) -> SyncResult:
    return SyncResult(mid, ref, method, r.offset, r.correlation, r.match_duration, r.windows_verified,
                      r.windows_total, r.drift_ppm, r.confidence, False, list(r.notes))


def synchronize(inputs: list[SyncInput], master_id: str, ffmpeg: str, cache_dir: Path,
                progress: Callable[[int, str], None], token: CancelToken,
                rate: int = ANALYSIS_RATE) -> dict[str, SyncResult]:
    """Every recording is measured against the master; failures fall back to other synced recordings.

    All offsets are expressed against the master timeline directly (chained offsets are summed once),
    so errors do not accumulate through repeated re-referencing.
    """
    by_id = {i.id: i for i in inputs}
    if master_id not in by_id:
        raise MediaError("Master audio is not part of the analysis")
    results: dict[str, SyncResult] = {master_id: SyncResult(master_id, master_id, "reference", confidence="High", windows_verified=0)}
    audio: dict[str, AnalysisAudio] = {}
    n = len(inputs)
    for k, item in enumerate(inputs):
        if token.cancelled:
            raise Cancelled()
        progress(int(35 * k / n), f"Extracting audio: {item.name}")
        if item.stream_index is None:
            results[item.id] = SyncResult(item.id, master_id, "waveform", notes=["No audio stream in this file"])
            continue
        try:
            audio[item.id] = extract_analysis_audio(item.path, item.stream_index, ffmpeg, cache_dir, rate, token)
        except MediaError as exc:
            results[item.id] = SyncResult(item.id, master_id, "waveform", notes=[str(exc)])
            continue
        if audio[item.id].silent:
            results[item.id] = SyncResult(item.id, master_id, "waveform", notes=["Recording is silent"])
            del audio[item.id]
    if master_id not in audio:
        raise MediaError("Master audio could not be decoded or is silent: " + "; ".join(results[master_id].notes or ["unknown"]))
    targets = [i for i in inputs if i.id != master_id and i.id in audio]
    pairs: dict[tuple[str, str], PairResult] = {}
    for k, item in enumerate(targets):
        if token.cancelled:
            raise Cancelled()
        base = 35 + int(55 * k / max(1, len(targets)))
        span = 55 / max(1, len(targets))
        progress(base, f"Synchronizing {item.name} to master")
        r = correlate_pair(audio[master_id].path, audio[item.id].path, token=token,
                           progress=lambda p, m, b=base, s=span, nm=item.name: progress(int(b + s * p / 100), f"{nm}: {m}"))
        pairs[(master_id, item.id)] = r
        results[item.id] = _from_pair(item.id, master_id, "waveform", r)
    # Fallback: weak/failed items are matched against recordings that already synced. Candidates are ordered by
    # clock hint proximity (hints never decide an offset, only which pairs are tried first) and capped, so
    # large camera-only projects stay tractable. Repeated passes let chains grow (A->master, B->A, C->B).
    max_candidates = 8
    for _pass in range(3):
        weak = [i for i in targets if _RANK[results[i.id].confidence] < 2]
        if not weak:
            break
        progressed = False
        for k, item in enumerate(weak):
            good = [i for i in targets if _RANK[results[i.id].confidence] >= 2 and i.id != item.id]
            good.append(by_id[master_id])

            def dist(i: SyncInput, item=item) -> tuple:
                d = abs(i.hint - item.hint) if (i.hint is not None and item.hint is not None) else float("inf")
                return (d, -_RANK.get(results[i.id].confidence, 3))
            for ref in sorted(good, key=dist)[:max_candidates]:
                if token.cancelled:
                    raise Cancelled()
                if ref.id == master_id and (master_id, item.id) in pairs:
                    continue
                progress(90 + int(9 * k / max(1, len(weak))), f"Trying {item.name} against {ref.name}")
                r = correlate_pair(audio[ref.id].path, audio[item.id].path, token=token)
                if _RANK[r.confidence] < 2:
                    continue
                rr = results[ref.id]
                conf = r.confidence if _RANK[r.confidence] <= _RANK[rr.confidence] else rr.confidence
                res = _from_pair(item.id, ref.id, f"waveform via {ref.name}", r)
                res.offset = r.offset + rr.offset
                res.drift_ppm = r.drift_ppm + rr.drift_ppm
                res.confidence = "Medium" if conf == "High" else conf   # chained matches never claim High
                res.notes.append(f"Matched against {ref.name}, then combined with its offset to the master")
                results[item.id] = res
                progressed = True
                break
        if not progressed:
            break
    progress(100, "Synchronization complete")
    return results
