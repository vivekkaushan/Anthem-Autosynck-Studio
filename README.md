# AutoSync Studio

Synchronize multi-camera video with external audio recorders by audio waveform, entirely offline, and (coming
soon) export a Premiere Pro compatible Final Cut Pro 7 XML.

## Download and install (no programming needed)

Go to the **[Releases](../../releases/latest)** page and download the file for your computer.

| Computer | File | Install |
|---|---|---|
| **Windows 10/11** | `AutoSyncStudio-Windows.zip` | Right-click → *Extract All…*, open the folder, double-click **AutoSyncStudio.exe**. If Windows SmartScreen warns, click *More info → Run anyway*. |
| **Mac with Apple chip (M1/M2/M3/M4)** | `AutoSyncStudio-macOS-AppleSilicon.dmg` | Open the .dmg, drag **AutoSync Studio** into *Applications*. The first time, **right-click the app → Open → Open** (the app is not yet signed with an Apple Developer ID). |
| **Mac with Intel chip** | `AutoSyncStudio-macOS-Intel.dmg` | Same as above. |

Not sure which Mac you have? Apple menu → *About This Mac*.
FFmpeg is included; there is nothing else to install.

## How to use

1. **Import Folder** and choose the folder that holds `Camera 1`, `Camera 2`, `Audio 1`… Each sub-folder becomes one
   group, and all clips inside share one camera track. (Or use *Import Media* / *Add Camera* / *Add Audio*.)
2. Select your recorder's audio file and click **Set Master Audio**.
3. Click **Analyze & Sync**. Offsets, confidence (High / Medium / Low), drift and notes appear in **Sync Results**.

## Status

| Area | State |
|---|---|
| Media import, FFprobe inspection, folder groups | Done |
| Audio extraction + cache | Done |
| Waveform sync (offset, drift, confidence, camera-to-camera fallback) | Done, tested on synthetic audio (error ≈ 0.02 ms) |
| Timecode sync, audio fingerprint fallback | Planned |
| Timeline with waveforms, manual offsets | Planned |
| Premiere XML export | Planned |
| Save / open projects | Planned |

## For developers

    python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python main.py            # needs ffmpeg/ffprobe on PATH or in third_party/ffmpeg
    python -m pytest          # 39 tests, synthetic audio with known offsets

Python 3.12 or 3.13 recommended (PySide6 may lag brand-new Python releases). macOS users can double-click `run.command`.

### Releases
Pushing a tag like `v0.1.0` makes GitHub Actions build the Windows zip and both macOS disk images and attach them to
a Release. Every push to `main` also builds them as downloadable *Artifacts* on the Actions tab.
FFmpeg is bundled as separate LGPL executables; see `THIRD_PARTY_NOTICES.md`.

### Known limitations
- Builds are **unsigned**: Windows SmartScreen and macOS Gatekeeper show a warning on first launch. Removing it needs a
  code-signing certificate (Windows) or Apple Developer ID + notarization (macOS).
- The CI workflow has not yet run on GitHub; the first run may need small fixes.
