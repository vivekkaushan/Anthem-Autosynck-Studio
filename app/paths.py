"""Filesystem locations, resolved for both source and PyInstaller-frozen runs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app import APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory holding bundled resources / third_party binaries."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Per-user writable data directory (config, logs, caches, autosave)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_NAME.replace(" ", "")
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    p = user_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = user_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def autosave_dir() -> Path:
    p = user_data_dir() / "autosave"
    p.mkdir(parents=True, exist_ok=True)
    return p
