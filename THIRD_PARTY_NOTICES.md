# Third-party software

AutoSync Studio bundles or uses the following. Each remains under its own licence.

| Component | Licence | Notes |
|---|---|---|
| **FFmpeg / FFprobe** | LGPL v2.1+ | Distributed as separate executables, built **without** `--enable-gpl` or `--enable-nonfree`. Source: https://ffmpeg.org/releases/ . The macOS binaries are built from the unmodified FFmpeg source in the build workflow (`.github/workflows/build.yml` shows the exact configure flags); the Windows binaries come from the BtbN LGPL builds (https://github.com/BtbN/FFmpeg-Builds). You may replace the bundled `ffmpeg`/`ffprobe` with your own LGPL build. |
| **Qt for Python (PySide6)** | LGPL v3 | Dynamically linked; shipped as separate shared libraries so it can be replaced. https://www.qt.io/qt-for-python |
| **NumPy** | BSD-3-Clause | |
| **SciPy** | BSD-3-Clause | |
| **python-soundfile / libsndfile** | BSD-3-Clause / LGPL-2.1 | |
| **PyInstaller** (build tool) | GPL-2.0 with bootloader exception | Does not impose a licence on the packaged application. |

This file is informational and not legal advice; review before commercial distribution.
