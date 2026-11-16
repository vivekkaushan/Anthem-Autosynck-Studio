"""Check for a newer release in the background."""
from __future__ import annotations

from core.updates import check_for_update
from workers.base import Job


def make_update_job(current: str) -> Job:
    """Result: UpdateInfo | None (None = up to date)."""
    def run(progress, token):
        return check_for_update(current)
    return Job(run, "update-check")
