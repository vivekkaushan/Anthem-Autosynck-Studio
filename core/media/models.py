"""Media item model shared by the UI, importer and sync engine."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v"}
AUDIO_EXTS = {".wav", ".mp3", ".aac", ".m4a", ".aiff", ".aif", ".flac"}


class MediaKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"


def classify(path: str | Path) -> MediaKind | None:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXTS:
        return MediaKind.VIDEO
    if ext in AUDIO_EXTS:
        return MediaKind.AUDIO
    return None


@dataclass
class MediaItem:
    path: str
    kind: MediaKind
    role: str = ""            # e.g. "CAM 01", "AUDIO 01"
    name: str = ""            # user-editable display name
    session: str = "Session 1"
    is_master: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    info: object | None = None   # core.media.probe.ProbeResult once probed
    error: str = ""             # probe failure message (missing/corrupt media)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = Path(self.path).name

    @property
    def exists(self) -> bool:
        return Path(self.path).is_file()


def natural_key(path: str | Path) -> list:
    """Sort 'clip2' before 'clip10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(path))]


def role_from_group(name: str, kind: MediaKind) -> str | None:
    """'Camera 3' -> 'CAM 03', 'Audio 2' -> 'AUDIO 02'. None when the folder name carries no number."""
    m = re.search(r"(\d+)\s*$", name.strip())
    if not m:
        return None
    return f"{'CAM' if kind is MediaKind.VIDEO else 'AUDIO'} {int(m.group(1)):02d}"
