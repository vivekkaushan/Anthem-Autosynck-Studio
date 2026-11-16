"""Dependency checks: Python packages and FFmpeg/FFprobe binaries."""
from __future__ import annotations

import importlib
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.paths import resource_root

log = logging.getLogger(__name__)

REQUIRED_PACKAGES = ("PySide6", "numpy", "scipy", "soundfile")


@dataclass(frozen=True)
class DependencyReport:
    missing_packages: tuple[str, ...]
    ffmpeg: str | None
    ffprobe: str | None
    ffmpeg_version: str | None
    python_ok: bool

    @property
    def ok(self) -> bool:
        return self.python_ok and not self.missing_packages and bool(self.ffmpeg and self.ffprobe)

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.python_ok:
            out.append("Python 3.12 or newer is required.")
        for p in self.missing_packages:
            out.append(f"Python package missing: {p}")
        if not self.ffmpeg:
            out.append("FFmpeg not found (bundle it in third_party/ffmpeg or install it on PATH).")
        if not self.ffprobe:
            out.append("FFprobe not found (bundle it in third_party/ffmpeg or install it on PATH).")
        return out


def _exe(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def find_binary(name: str, configured: str = "") -> str | None:
    """Resolve a binary: explicit config > bundled third_party > PATH."""
    if configured and Path(configured).is_file():
        return configured
    bundled = resource_root() / "third_party" / "ffmpeg" / _exe(name)
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)


def _version(ffmpeg: str) -> str | None:
    try:
        out = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        log.exception("Could not run %s -version", ffmpeg)
        return None
    m = re.search(r"version\s+(\S+)", out)
    return m.group(1) if m else None


def check_dependencies(ffmpeg_path: str = "", ffprobe_path: str = "") -> DependencyReport:
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    ffmpeg = find_binary("ffmpeg", ffmpeg_path)
    ffprobe = find_binary("ffprobe", ffprobe_path)
    report = DependencyReport(
        tuple(missing), ffmpeg, ffprobe, _version(ffmpeg) if ffmpeg else None, sys.version_info >= (3, 12)
    )
    log.info("Dependencies: ffmpeg=%s (%s) ffprobe=%s missing=%s",
             report.ffmpeg, report.ffmpeg_version, report.ffprobe, report.missing_packages)
    return report
