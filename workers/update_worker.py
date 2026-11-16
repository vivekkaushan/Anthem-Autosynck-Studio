"""Check for a newer release in the background."""
from __future__ import annotations

from core.updates import check_for_update
from workers.base import Job


def make_update_job(current: str) -> Job:
    """Result: UpdateInfo | None (None = up to date)."""
    def run(progress, token):
        return check_for_update(current)
    return Job(run, "update-check")


def make_install_job(url: str, ctx) -> Job:
    """Download the update and prepare its installer script. Result: Path to the script."""
    from core.selfupdate import prepare

    def run(progress, token):
        return prepare(url, ctx, progress, token)
    return Job(run, "update-download")
