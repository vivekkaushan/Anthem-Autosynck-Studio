"""In-app update: download the release for this computer and swap it in after the app closes.

Only works for an installed (frozen) copy. Files downloaded by the app carry no browser quarantine flag, so an
unsigned update is not blocked by Gatekeeper/SmartScreen a second time. If the swap cannot be done (for example no
write permission), the downloaded file is opened for a manual install instead; nothing is ever half-replaced.
"""
from __future__ import annotations

import os
import shlex
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.errors import Cancelled
from core.updates import _ssl_context


@dataclass(frozen=True)
class InstallContext:
    kind: str          # "mac" | "win"
    target: Path       # mac: the .app bundle; win: the folder holding the .exe
    exe: str = ""      # win: exe file name


def install_context() -> InstallContext | None:
    """Where the running, installed app lives; None when running from source (self-update is off)."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        app = next((p for p in exe.parents if p.suffix == ".app"), None)
        return InstallContext("mac", app) if app else None
    if sys.platform.startswith("win"):
        return InstallContext("win", exe.parent, exe.name)
    return None


def download(url: str, dest: Path, progress: Callable[[int, str], None], token, timeout: float = 30.0) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "AnthemAutoSynckStudio"})
    ctx: ssl.SSLContext | None = _ssl_context() if url.startswith("https") else None
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if token.cancelled:
                    raise Cancelled()
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if total:
                    progress(int(90 * got / total), f"Downloading update… {got / 1e6:.0f} / {total / 1e6:.0f} MB")
                else:
                    progress(45, f"Downloading update… {got / 1e6:.0f} MB")
        if total and got != total:
            raise OSError(f"Download incomplete ({got} of {total} bytes)")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def mac_script(pid: int, dmg: Path, target: Path, log: Path) -> str:
    q = shlex.quote
    return f"""#!/bin/bash
exec >{q(str(log))} 2>&1
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
TARGET={q(str(target))}
DMG={q(str(dmg))}
MNT=$(mktemp -d)
if ! hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG"; then open "$DMG"; exit 1; fi
SRC=$(find "$MNT" -maxdepth 1 -name '*.app' | head -1)
OK=0
if [ -n "$SRC" ] && ditto "$SRC" "$TARGET.new"; then
  if mv "$TARGET" "$TARGET.old"; then
    if mv "$TARGET.new" "$TARGET"; then OK=1; rm -rf "$TARGET.old"; else mv "$TARGET.old" "$TARGET"; fi
  fi
fi
hdiutil detach "$MNT" -quiet
rm -rf "$TARGET.new"
if [ "$OK" = 1 ]; then
  xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
  open "$TARGET"
else
  open "$DMG"
fi
"""


def win_script(pid: int, src_dir: Path, dest_dir: Path, exe: str, log: Path) -> str:
    return f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
xcopy "{src_dir}\\*" "{dest_dir}\\" /E /Y /I /Q >"{log}" 2>&1
if errorlevel 1 (
  explorer "{src_dir}"
  exit /b 1
)
start "" "{dest_dir}\\{exe}"
"""


def prepare(url: str, ctx: InstallContext, progress: Callable[[int, str], None], token) -> Path:
    """Download (and, on Windows, unpack) the update; returns the script that installs it once the app has quit."""
    work = Path(tempfile.mkdtemp(prefix="anthem-update-"))
    name = url.rsplit("/", 1)[-1] or "update"
    pkg = download(url, work / name, progress, token)
    log = work / "update.log"
    if ctx.kind == "mac":
        script = work / "update.sh"
        script.write_text(mac_script(os.getpid(), pkg, ctx.target, log))
        script.chmod(0o755)
        return script
    progress(92, "Unpacking update…")
    out = work / "unpacked"
    with zipfile.ZipFile(pkg) as z:
        z.extractall(out)
    src = next((p.parent for p in out.rglob(ctx.exe)), None)
    if src is None:
        raise OSError(f"The update does not contain {ctx.exe}")
    script = work / "update.bat"
    script.write_text(win_script(os.getpid(), src, ctx.target, ctx.exe, log))
    return script


def launch(script: Path) -> None:
    """Start the installer script detached from this process (it waits for the app to exit)."""
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "DETACHED_PROCESS", 8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
