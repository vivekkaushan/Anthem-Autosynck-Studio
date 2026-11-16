"""Background job: compute waveform peaks from cached analysis audio."""
from __future__ import annotations

from pathlib import Path

from core.media.extract import analysis_wav_path
from core.media.waveform import load_or_compute
from workers.base import Job


def make_peaks_job(items: list[tuple[str, str, int]], cache_dir: Path) -> Job:
    """items = [(media_id, source_path, audio_stream_index)]. Result: dict media_id -> ndarray (n, 2)."""
    def run(progress, token):
        out = {}
        for i, (mid, src, stream) in enumerate(items):
            if token.cancelled:
                break
            progress(int(100 * i / max(1, len(items))), "Drawing waveforms")
            wav = analysis_wav_path(src, stream, cache_dir)
            if wav.is_file():
                out[mid] = load_or_compute(wav, token)
        progress(100, "Waveforms ready")
        return out
    return Job(run, "peaks")
