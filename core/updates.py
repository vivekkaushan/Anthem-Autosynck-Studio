"""Update check against the project's GitHub Releases. Read-only: never downloads or installs anything by itself."""
from __future__ import annotations

import json
import logging
import platform
import re
import ssl
import sys
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

REPO = "vivekkaushan/Anthem-Autosynck-Studio"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    version: str          # e.g. "0.2.0"
    page_url: str         # release page
    asset_name: str       # installer for this computer, "" if none matched
    asset_url: str        # direct download, "" if none matched
    notes: str = ""

    @property
    def download_url(self) -> str:
        return self.asset_url or self.page_url


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.2.10' -> (0, 2, 10). Non-numeric suffixes (e.g. '-beta') are ignored; unparsable -> ()."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def platform_key(plat: str | None = None, machine: str | None = None) -> str:
    """'windows' | 'macos-applesilicon' | 'macos-intel' | 'other' - matches the release file names."""
    plat, machine = plat or sys.platform, (machine or platform.machine()).lower()
    if plat.startswith("win"):
        return "windows"
    if plat == "darwin":
        return "macos-applesilicon" if machine in ("arm64", "aarch64") else "macos-intel"
    return "other"


def pick_asset(assets: list[dict], key: str) -> tuple[str, str]:
    """Choose the release file for this computer by its name; returns (name, url) or ('', '')."""
    wanted = {"windows": ("windows",), "macos-applesilicon": ("applesilicon",), "macos-intel": ("intel",)}.get(key)
    if not wanted:
        return "", ""
    for a in assets or []:
        name = str(a.get("name", ""))
        low = name.lower()
        if any(w in low for w in wanted) and low.endswith((".zip", ".dmg")):
            return name, str(a.get("browser_download_url", ""))
    return "", ""


def parse_release(data: dict, current: str, key: str) -> UpdateInfo | None:
    """UpdateInfo if the release is newer than `current` and is a normal (non-draft, non-prerelease) release."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name", ""))
    if not is_newer(tag, current):
        return None
    name, url = pick_asset(data.get("assets", []), key)
    return UpdateInfo(".".join(map(str, parse_version(tag))), str(data.get("html_url", "")), name, url, str(data.get("body") or "")[:2000])


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:                      # certifi missing: fall back to the system store
        return ssl.create_default_context()


def check_for_update(current: str, *, url: str = LATEST_URL, timeout: float = 8.0, key: str | None = None) -> UpdateInfo | None:
    """Ask GitHub for the latest release. Returns None when up to date; raises OSError/ValueError when it cannot be checked."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "AnthemAutoSynckStudio"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_release(data, current, key or platform_key())
