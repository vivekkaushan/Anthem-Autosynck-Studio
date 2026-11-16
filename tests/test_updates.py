import json

import pytest

from core import updates as u


def test_version_parsing_and_comparison():
    assert u.parse_version("v0.2.10") == (0, 2, 10)
    assert u.parse_version("1.0-beta") == (1, 0)
    assert u.parse_version("garbage") == ()
    assert u.is_newer("v0.2.0", "0.1.0") and u.is_newer("0.10.0", "0.9.9") and u.is_newer("1.0.1", "1.0")
    assert not u.is_newer("0.1.0", "0.1.0") and not u.is_newer("v0.1", "0.1.0") and not u.is_newer("0.0.9", "0.1.0")
    assert not u.is_newer("nonsense", "0.1.0")          # never claim an update from a tag we cannot read


def test_platform_key():
    assert u.platform_key("win32", "AMD64") == "windows"
    assert u.platform_key("darwin", "arm64") == "macos-applesilicon"
    assert u.platform_key("darwin", "x86_64") == "macos-intel"
    assert u.platform_key("linux", "x86_64") == "other"


ASSETS = [{"name": "AutoSyncStudio-Windows.zip", "browser_download_url": "https://x/win.zip"},
          {"name": "AutoSyncStudio-macOS-AppleSilicon.dmg", "browser_download_url": "https://x/arm.dmg"},
          {"name": "AutoSyncStudio-macOS-Intel.dmg", "browser_download_url": "https://x/intel.dmg"},
          {"name": "source.tar.gz", "browser_download_url": "https://x/src"}]


def test_asset_selection_per_platform():
    assert u.pick_asset(ASSETS, "windows") == ("AutoSyncStudio-Windows.zip", "https://x/win.zip")
    assert u.pick_asset(ASSETS, "macos-applesilicon")[1] == "https://x/arm.dmg"
    assert u.pick_asset(ASSETS, "macos-intel")[1] == "https://x/intel.dmg"
    assert u.pick_asset(ASSETS, "other") == ("", "")
    assert u.pick_asset([], "windows") == ("", "")


def rel(tag, **kw):
    return {"tag_name": tag, "html_url": "https://github.com/r/releases/tag/" + tag, "assets": ASSETS, "body": "notes", **kw}


def test_parse_release():
    info = u.parse_release(rel("v0.2.0"), "0.1.0", "macos-applesilicon")
    assert info and info.version == "0.2.0" and info.download_url == "https://x/arm.dmg" and info.notes == "notes"
    assert u.parse_release(rel("v0.1.0"), "0.1.0", "windows") is None                  # same version
    assert u.parse_release(rel("v0.3.0", prerelease=True), "0.1.0", "windows") is None  # not offered
    assert u.parse_release(rel("v0.3.0", draft=True), "0.1.0", "windows") is None
    assert u.parse_release({"message": "Not Found"}, "0.1.0", "windows") is None
    other = u.parse_release(rel("v0.2.0"), "0.1.0", "other")
    assert other.asset_url == "" and other.download_url == other.page_url             # falls back to the release page


def test_check_for_update_reads_http(monkeypatch):
    class Resp:
        def __init__(self, data): self.data = data
        def read(self): return json.dumps(self.data).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(u.urllib.request, "urlopen", lambda req, timeout, context: Resp(rel("v1.0.0")))
    assert u.check_for_update("0.1.0", key="windows").download_url == "https://x/win.zip"
    assert u.check_for_update("1.0.0", key="windows") is None


def test_offline_raises_instead_of_pretending(monkeypatch):
    def boom(*a, **k): raise OSError("offline")
    monkeypatch.setattr(u.urllib.request, "urlopen", boom)
    with pytest.raises(OSError):
        u.check_for_update("0.1.0")


def test_button_shows_only_for_newer_release(qapp):
    from app.config import Config
    from app.dependencies import check_dependencies
    from ui.main_window import MainWindow
    w = MainWindow(Config(), check_dependencies())
    assert not w.b_update.isVisible() and not w.b_update.isVisibleTo(w)
    w._update_manual = False
    w._on_update_result(None)
    assert not w.b_update.isVisibleTo(w)
    w._on_update_result(u.parse_release(rel("v9.9.9"), "0.1.0", "macos-applesilicon"))
    assert w.b_update.isVisibleTo(w) and "9.9.9" in w.b_update.text()
    w._on_update_failed("offline")                 # silent when automatic; keeps working
    assert w.config.check_updates is True
    w.a_auto_updates.setChecked(False); w._toggle_auto_updates()
    assert w.config.check_updates is False
