"""Probe many media files in the background; per-file failures do not abort the batch."""
from __future__ import annotations

from app.errors import MediaError
from core.media.probe import ProbeResult, probe_file
from workers.base import CancelToken, Job


def make_probe_job(items: list[tuple[str, str]], ffprobe: str) -> Job:
    """items = [(media_id, path)]. Result: dict media_id -> ProbeResult | MediaError."""
    def run(progress, token: CancelToken):
        out: dict[str, ProbeResult | MediaError] = {}
        for i, (mid, path) in enumerate(items):
            if token.cancelled:
                break
            progress(int(100 * i / max(1, len(items))), f"Probing {path.rsplit('/', 1)[-1]}")
            try:
                out[mid] = probe_file(path, ffprobe)
            except MediaError as exc:
                out[mid] = exc
        progress(100, "Probing complete")
        return out
    return Job(run, "probe")
