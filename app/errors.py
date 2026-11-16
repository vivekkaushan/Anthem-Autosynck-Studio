"""Exception hierarchy. Errors are never swallowed silently; they are logged and surfaced."""
from __future__ import annotations


class AutoSyncError(Exception):
    """Base class for all application errors."""


class DependencyError(AutoSyncError):
    """A required external dependency (FFmpeg, FFprobe, Python package) is missing."""


class MediaError(AutoSyncError):
    """A media file is missing, unreadable or corrupted."""


class SyncError(AutoSyncError):
    """Synchronization could not be computed."""


class ExportError(AutoSyncError):
    """Export validation or writing failed."""


class ProjectError(AutoSyncError):
    """Project database failure."""


class Cancelled(Exception):
    """Raised inside a worker when the user cancels. Not an error."""
