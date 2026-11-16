import subprocess
import zipfile
from pathlib import Path

import pytest

from app.errors import Cancelled
from core import selfupdate as su
from workers.base import CancelToken


def test_download_with_progress_and_cancel(tmp_path):
    src = tmp_path / "pkg.zip"
    src.write_bytes(b"x" * 3_000_000)
    seen = []
    out = su.download(src.as_uri(), tmp_path / "dl.zip", lambda p, m: seen.append(p), CancelToken())
    assert out.read_bytes() == src.read_bytes() and not list(tmp_path.glob("*.part"))
    tok = CancelToken(); tok.cancel()
    with pytest.raises(Cancelled):
        su.download(src.as_uri(), tmp_path / "dl2.zip", lambda p, m: None, tok)
    assert not (tmp_path / "dl2.zip").exists() and not list(tmp_path.glob("*.part"))


def test_mac_script_is_valid_bash_and_quotes_paths(tmp_path):
    s = su.mac_script(1234, tmp_path / "a b.dmg", Path("/Applications/Anthem's App.app"), tmp_path / "log")
    f = tmp_path / "u.sh"; f.write_text(s)
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert "mv \"$TARGET\" \"$TARGET.old\"" in s and "mv \"$TARGET.old\" \"$TARGET\"" in s     # rolls back on failure


def test_windows_prepare_unpacks_and_writes_bat(tmp_path, monkeypatch):
    z = tmp_path / "AutoSyncStudio-Windows.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("AutoSyncStudio/AutoSyncStudio.exe", b"MZ")
        zf.writestr("AutoSyncStudio/_internal/x.dll", b"1")
    ctx = su.InstallContext("win", tmp_path / "installed", "AutoSyncStudio.exe")
    script = su.prepare(z.as_uri(), ctx, lambda p, m: None, CancelToken())
    text = script.read_text()
    assert script.suffix == ".bat" and "xcopy" in text and "AutoSyncStudio.exe" in text
    assert (script.parent / "unpacked" / "AutoSyncStudio" / "AutoSyncStudio.exe").is_file()


def test_not_frozen_means_no_self_update():
    assert su.install_context() is None
