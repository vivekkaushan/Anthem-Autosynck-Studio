# PyInstaller spec for AutoSync Studio (one-folder build; .app bundle on macOS).
# Build from the repo root:  pyinstaller packaging/autosync.spec --noconfirm
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
exe_ext = ".exe" if sys.platform == "win32" else ""

# Bundled FFmpeg/FFprobe (LGPL builds) are placed in third_party/ffmpeg by the build workflow or by hand.
binaries = []
for name in ("ffmpeg", "ffprobe"):
    p = ROOT / "third_party" / "ffmpeg" / (name + exe_ext)
    if p.is_file():
        binaries.append((str(p), "third_party/ffmpeg"))
    else:
        print(f"WARNING: {p} not found - the build will NOT contain {name}")
datas = [(str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")]
for lic in (ROOT / "third_party" / "ffmpeg").glob("LICENSE*"):
    datas.append((str(lic), "third_party/ffmpeg"))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "pkg_resources", "setuptools", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AutoSyncStudio", console=False, debug=False,
          strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AutoSyncStudio")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="AutoSync Studio.app", bundle_identifier="com.autosyncstudio.app",
                 info_plist={"CFBundleName": "AutoSync Studio", "CFBundleDisplayName": "AutoSync Studio",
                             "CFBundleShortVersionString": "0.1.0", "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "11.0",
                             "NSDesktopFolderUsageDescription": "AutoSync Studio reads media you choose.",
                             "NSRemovableVolumesUsageDescription": "AutoSync Studio reads media you choose.",
                             "NSNetworkVolumesUsageDescription": "AutoSync Studio reads media you choose."})
