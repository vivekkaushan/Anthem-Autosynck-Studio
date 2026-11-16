"""Background job: extract audio and synchronize all recordings to the master."""
from __future__ import annotations

from pathlib import Path

from core.synchronization.engine import SyncInput, synchronize
from workers.base import Job


def make_sync_job(inputs: list[SyncInput], master_id: str, ffmpeg: str, cache_dir: Path) -> Job:
    return Job(lambda progress, token: synchronize(inputs, master_id, ffmpeg, cache_dir, progress, token), "sync")
