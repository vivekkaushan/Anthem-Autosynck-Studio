"""Persistent user configuration (JSON). Corrupt config is backed up, never silently dropped."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from app.paths import user_data_dir

log = logging.getLogger(__name__)


@dataclass
class Config:
    analysis_sample_rate: int = 16000
    autosave_interval_s: int = 120
    recent_projects: list[str] = field(default_factory=list)
    ffmpeg_path: str = ""   # empty = auto-detect
    ffprobe_path: str = ""
    last_media_dir: str = ""
    window_geometry: str = ""  # base64 Qt geometry
    check_updates: bool = True  # look for a newer release on GitHub at startup (the only network access the app makes)

    @staticmethod
    def path() -> Path:
        return user_data_dir() / "config.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or cls.path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in raw.items() if k in known})
        except (OSError, ValueError, TypeError) as exc:
            backup = path.with_suffix(".json.corrupt")
            log.error("Config unreadable (%s); backing up to %s and using defaults", exc, backup)
            try:
                path.replace(backup)
            except OSError:
                log.exception("Could not back up corrupt config")
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or self.path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)

    def add_recent(self, project_path: str, limit: int = 10) -> None:
        self.recent_projects = [project_path] + [p for p in self.recent_projects if p != project_path]
        del self.recent_projects[limit:]
