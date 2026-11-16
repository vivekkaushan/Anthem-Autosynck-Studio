"""Main application window: toolbar, library, workspace, inspector, status area."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QToolButton,
                               QVBoxLayout, QWidget, QHBoxLayout)

from app import APP_NAME
from app.config import Config
from app.dependencies import DependencyReport
from app.state import ProjectState
from core.media.models import AUDIO_EXTS, VIDEO_EXTS, MediaKind
from workers.probe_worker import make_probe_job
from workers.sync_worker import make_sync_job
from core.synchronization.engine import SyncInput
from app.paths import cache_dir
from ui.chrome import BottomBar, HeaderBar, Rail, SummaryBar, app_icon
from ui.inspector import Inspector
from ui.player import SyncPlayer
from ui.media_library import MediaLibrary
from ui.timeline_view import TimelinePanel, fmt_time
from workers.update_worker import make_update_job
from workers.waveform_worker import make_peaks_job
from app import __version__

log = logging.getLogger(__name__)

VIDEO_FILTER = "Video (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTS)) + ")"
AUDIO_FILTER = "Audio (" + " ".join(f"*{e}" for e in sorted(AUDIO_EXTS)) + ")"
ALL_FILTER = "Media (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTS | AUDIO_EXTS)) + ")"


def _clock_hint(m) -> float | None:
    """Approximate wall-clock seconds from container creation time. Only orders candidate pairs; never an offset."""
    ct = getattr(m.info, "creation_time", None) if m.info is not None else None
    if not ct:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(ct).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class MainWindow(QMainWindow):
    def __init__(self, config: Config, deps: DependencyReport) -> None:
        super().__init__()
        self.config, self.deps = config, deps
        self.state = ProjectState()
        self._jobs: list = []
        self._sync_job = None
        self._update_job = None
        self._update_manual = False
        self.setMinimumSize(1000, 640)
        self.resize(1440, 860)
        self.setWindowIcon(app_icon())

        self.library = MediaLibrary(self.state)
        self.timeline_panel = TimelinePanel(self.state)
        self.timeline = self.timeline_panel.view
        self.timeline.clip_selected.connect(self._on_selection)
        self.inspector = Inspector(self.state)
        self.library.selection_changed.connect(self._on_selection)
        self.player = SyncPlayer()
        self.player.position_changed.connect(self._on_play_position)
        self.player.stopped.connect(self._on_play_stopped)
        self.player.failed.connect(lambda msg: self.set_status(f"Playback failed: {msg}"))
        self.inspector.review.listen_requested.connect(self.toggle_play)

        self.hsplit = QSplitter(Qt.Horizontal)
        for w in (self.library, self.timeline_panel, self.inspector):
            self.hsplit.addWidget(w)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([270, 800, 330])
        self.hsplit.setChildrenCollapsible(False)

        self.rail = Rail()
        self.header = HeaderBar()
        self.summary = SummaryBar()
        self.bottom = BottomBar()
        self.progress = self.bottom.progress
        self.rail.library_toggled.connect(self.library.setVisible)
        self.rail.inspector_toggled.connect(self.inspector.setVisible)
        self.rail.help_clicked.connect(self._help)
        self.bottom.prev_clicked.connect(lambda: self._jump(-1))
        self.bottom.next_clicked.connect(lambda: self._jump(+1))
        self.timeline.playhead_changed.connect(self._on_playhead)
        self.bottom.b_play.clicked.connect(self.toggle_play)

        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        for w in (self.header, self.summary):
            cl.addWidget(w)
        cl.addWidget(self.hsplit, 1)
        cl.addWidget(self.bottom)
        root = QWidget()
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.rail)
        rl.addWidget(col, 1)
        self.setCentralWidget(root)

        self._build_actions()
        self._build_header()
        self._init_deps_label()
        self._refresh_actions()
        self._refresh_summary()
        for sig in (self.state.changed, self.state.media_changed, self.state.timeline_changed):
            sig.connect(self._refresh_summary)
        self.state.changed.connect(self._refresh_actions)
        self.state.changed.connect(self._update_title)
        self._update_title()
        if config.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(config.window_geometry.encode()))

    # ---- actions + header buttons ------------------------------------------------
    def _act(self, text: str, slot, tip: str, *, pending: str = "") -> QAction:
        a = QAction(text, self)
        a.setToolTip(tip if not pending else f"{tip}\n(Not available yet: {pending})")
        a.triggered.connect(slot)
        a.setProperty("pending", pending)
        if pending:
            a.setEnabled(False)
        return a

    def _build_actions(self) -> None:
        A = self._act
        self.a_new = A("New Project", self.new_project, "Start an empty project")
        self.a_open = A("Open Project…", self._noop, "Open a saved project", pending="project database, Phase 9")
        self.a_save = A("Save Project", self._noop, "Save the project", pending="project database, Phase 9")
        self.a_import = A("Import Media…", self.import_media, "Import video and audio files")
        self.a_folder = A("Import Folder…", self.import_folder, "Import a folder; each sub-folder (Camera 1, Camera 2…) becomes one group and track")
        self.a_cam = A("Add Camera…", self.add_camera, "Add camera video recordings")
        self.a_aud = A("Add Audio…", self.add_audio, "Add external audio recordings")
        self.a_master = A("Set Reference", self.set_master, "Use the selected clip or audio file as the sync reference")
        self.a_sync = A("⚡ Synchronize", self.analyze, "Analyze and synchronize all recordings to the master audio")
        self.a_cancel = A("Cancel", self.cancel_analysis, "Cancel the running analysis")
        self.a_updates = A("Check for Updates…", self.check_updates_now, "Look for a newer version on GitHub")
        self.a_auto_updates = A("Check for updates at startup", self._toggle_auto_updates,
                                "Contact GitHub once at startup to see whether a newer version exists (nothing else is sent)")
        self.a_auto_updates.setCheckable(True)
        self.a_auto_updates.setChecked(self.config.check_updates)
        self.a_export = A("Export Timeline ↗", self.export_timeline, "Export the synchronized timeline as XML for Premiere Pro")

    def _bind(self, btn: QPushButton, action: QAction) -> QPushButton:
        btn.clicked.connect(action.trigger)

        def sync() -> None:
            btn.setEnabled(action.isEnabled())
            btn.setToolTip(action.toolTip())
        action.changed.connect(sync)
        sync()
        return btn

    def _menu_button(self, text: str, actions) -> QToolButton:
        b = QToolButton()
        b.setObjectName("menu")
        b.setText(text)
        b.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b)
        for a in actions:
            m.addSeparator() if a is None else m.addAction(a)
        b.setMenu(m)
        return b

    def _build_header(self) -> None:
        h = self.header
        self.b_update = self._mk("", "update")
        self.b_update.setVisible(False)
        self.b_update.clicked.connect(self._open_update)
        self._update_info = None
        h.add(self.b_update)
        h.add(self._bind(self._mk("New Project", "ghost"), self.a_new))
        h.add(self._menu_button("Project ▾", [self.a_open, self.a_save, None, self.a_updates, self.a_auto_updates]))
        h.add(self._menu_button("＋ Add Media ▾", [self.a_import, self.a_folder, self.a_cam, self.a_aud, None, self.a_master]))
        self.b_cancel = self._bind(self._mk("Cancel", "danger"), self.a_cancel)
        h.add(self.b_cancel)
        self.b_sync = self._bind(self._mk("⚡ Synchronize", "primary"), self.a_sync)
        h.add(self.b_sync)
        h.add(self._bind(self._mk("Export Timeline ↗", ""), self.a_export))

    @staticmethod
    def _mk(text: str, obj: str) -> QPushButton:
        b = QPushButton(text)
        if obj:
            b.setObjectName(obj)
        return b

    def _init_deps_label(self) -> None:
        if self.deps.ok:
            self.bottom.tagline.setText(f"Waveform-based synchronization • Multi-camera alignment • FFmpeg {self.deps.ffmpeg_version}")
        else:
            self.bottom.tagline.setText("⚠ dependencies missing: " + "; ".join(self.deps.problems()))
            self.bottom.tagline.setStyleSheet("color: #ffb45c; font-size: 11px;")

    def set_status(self, text: str) -> None:
        self.bottom.desc.setText(text)

    def _set_state(self, kind: str, text: str) -> None:
        self.bottom.set_state(kind, text)

    def _restore_state(self) -> None:
        tl = self.state.timeline
        if tl is None or not self.state.sync_results:
            self._set_state("ready", "Ready")
        else:
            ok, total = tl.counts
            self._set_state("done" if ok == total else "review", "Complete" if ok == total else "Needs review")

    # ---- summary tiles ---------------------------------------------------------------
    @staticmethod
    def _fps_text(fps: float) -> str:
        return f"{fps:.3f}".rstrip("0").rstrip(".") + " fps"

    def _refresh_summary(self) -> None:
        st = self.state
        tl = st.timeline
        s = self.summary
        s.t_tracks.set_value(str(len(self.timeline.lane_info())))
        s.t_clips.set_value(str(len(st.media)), "#39c6ec")
        results = [r for mid, r in st.sync_results.items() if (m := st.get(mid)) is not None and not m.is_master]
        if tl is not None and results:
            high = sum(1 for r in results if r.confidence == "High")
            pct = round(100 * high / len(results))
            s.t_conf.set_value(f"{pct}% High", "#69d5a5" if high == len(results) else "#ffb45c")
        else:
            s.t_conf.set_value("—")
        s.t_dur.set_value(fmt_time(float(tl.duration)) if tl is not None and st.sync_results else "—")
        if self._sync_job is not None:
            chip = "ANALYZING"
        elif tl is not None and st.sync_results:
            ok, total = tl.counts
            chip = "SYNCHRONIZED" if ok == total else "NEEDS REVIEW"
        else:
            chip = "READY TO SYNC" if st.media else "NO MEDIA YET"
        s.chip.setText(chip)
        fps = next((float(m.info.primary_video.frame_rate) for m in st.media if m.info is not None and m.info.primary_video), None)
        master = next((m for m in st.media if m.is_master), None)
        audio_src = master if master is not None and master.info is not None and master.info.audio else next(
            (m for m in st.media if m.info is not None and m.info.audio), None)
        rate = f"{audio_src.info.audio[0].sample_rate / 1000:g} kHz" if audio_src is not None else "—"
        s.set_formats(self._fps_text(fps) if fps else "—", rate)
        self.header.project.setText(f"●  {st.name}")

    # ---- transport -----------------------------------------------------------------------
    def _on_playhead(self, t: float) -> None:
        fps = next((float(m.info.primary_video.frame_rate) for m in self.state.media if m.info is not None and m.info.primary_video), None)
        if fps:
            n = max(1, round(fps))
            frames = int(round(t * fps))
            secs, ff = divmod(frames, n)
            self.bottom.timecode.setText(f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}:{ff:02d}")
        else:
            self.bottom.timecode.setText(fmt_time(t, True))

    def _jump(self, direction: int) -> None:
        tl = self.state.timeline
        if tl is None:
            return
        starts = sorted({float(c.start) for tr in tl.tracks for c in tr.clips})
        cur = self.timeline.playhead
        if direction < 0:
            target = max((x for x in starts if x < cur - 0.01), default=0.0)
        else:
            target = min((x for x in starts if x > cur + 0.01), default=cur)
        self.timeline.jump_to(target)

    # ---- updates ---------------------------------------------------------------------------
    def start_update_check(self, manual: bool = False) -> None:
        """Ask GitHub whether a newer release exists. Silent when offline unless the user asked (manual)."""
        if getattr(self, "_update_job", None) is not None:
            return
        if not manual and not self.config.check_updates:
            return
        self._update_manual = manual
        job = make_update_job(__version__)
        job.finished.connect(self._on_update_result)
        job.failed.connect(self._on_update_failed)
        job.done.connect(self._on_job_done)
        self._update_job = job
        self._jobs.append(job)
        job.start()

    def check_updates_now(self) -> None:
        self.start_update_check(manual=True)

    def _toggle_auto_updates(self) -> None:
        self.config.check_updates = self.a_auto_updates.isChecked()

    def _on_update_result(self, info) -> None:
        self._update_job = None
        if info is None:
            self.b_update.setVisible(False)
            if self._update_manual:
                QMessageBox.information(self, APP_NAME, f"You are up to date (version {__version__}).")
            return
        self._update_info = info
        self.b_update.setText(f"⬆ Update to v{info.version}")
        self.b_update.setToolTip(f"Version {info.version} is available (you have {__version__}).\n"
                                 + (f"Downloads {info.asset_name}." if info.asset_name else "Opens the release page.")
                                 + "\nInstall it over the old version; your settings are kept.")
        self.b_update.setVisible(True)
        if self._update_manual:
            self._open_update()

    def _on_update_failed(self, msg: str) -> None:
        self._update_job = None
        log.info("Update check failed: %s", msg)
        if self._update_manual:
            QMessageBox.information(self, APP_NAME, "Could not check for updates. Are you online?\n\n" + msg)

    def _open_update(self) -> None:
        info = self._update_info
        if info is None:
            return
        from core.selfupdate import install_context
        ctx = install_context()
        if ctx is None or not info.asset_url or getattr(self, "_install_job", None) is not None or self._sync_job is not None:
            QDesktopServices.openUrl(QUrl(info.download_url))
            self.set_status(f"Downloading version {info.version} in your browser. Open it when it finishes.")
            return
        if QMessageBox.question(self, APP_NAME, f"Install version {info.version} now?\n\nThe update downloads inside the app, "
                                "then Anthem Auto Synck Studio closes and reopens by itself.\nUnsaved work is not kept.") != QMessageBox.Yes:
            return
        from workers.update_worker import make_install_job
        job = make_install_job(info.asset_url, ctx)
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_update_ready)
        job.failed.connect(self._on_install_failed)
        job.cancelled.connect(self._on_install_failed)
        job.done.connect(self._on_job_done)
        self._install_job = job
        self._jobs.append(job)
        self.b_update.setEnabled(False)
        self._set_state("busy", "Updating")
        job.start()

    def _on_update_ready(self, script) -> None:
        from core.selfupdate import launch
        self._install_job = None
        self.set_status("Installing the update… the app will reopen")
        try:
            launch(script)
        except OSError as exc:
            self._on_install_failed(str(exc))
            return
        self.state.dirty = False
        QApplication.quit()

    def _on_install_failed(self, msg: str = "") -> None:
        self._install_job = None
        self.b_update.setEnabled(True)
        self._restore_state()
        info = self._update_info
        self.set_status("Update failed" + (f": {msg}" if msg else "") + ". Opening the download page instead.")
        if info is not None:
            QDesktopServices.openUrl(QUrl(info.download_url))

    def _help(self) -> None:
        QMessageBox.information(self, APP_NAME, "1. Add Media → Import Folder (Camera 1, Camera 2, Audio 1…)\n"
                                "2. Cameras only? Nothing else needed: the camera microphones are used and the longest clip is the starting reference.\n"
                                "   (Optional: select a clip or audio file, then Add Media → Set Reference to choose another.)\n"
                                "3. Synchronize, then check the confidence of each clip\n"
                                "4. Export Timeline (Premiere XML) arrives in a later release")

    # ---- state-driven UI --------------------------------------------------
    def _refresh_actions(self) -> None:
        # Actions marked "pending" stay disabled until their phase is implemented.
        self.a_master.setEnabled(bool(self.state.media))
        running = self._sync_job is not None
        with_audio = [m for m in self.state.media if m.info is not None and m.info.audio]
        others = [m for m in self.state.media if not m.is_master]
        ready = len(self.state.media) >= 2 and bool(with_audio)
        self.a_sync.setEnabled(not running and ready)
        self.a_cancel.setEnabled(running)
        self.bottom.b_play.setEnabled(bool(self.state.sync_results) and self.state.timeline is not None)
        self.a_export.setEnabled(bool(self.state.sync_results) and self.state.timeline is not None and not running)
        self.b_cancel.setVisible(running)
        tip = "Analyze and synchronize all recordings using their audio (camera microphones are fine)"
        if len(self.state.media) < 2:
            tip += "\n(Add at least two clips)"
        elif not with_audio:
            tip += "\n(Wait for media inspection, or add clips that contain audio)"
        self.a_sync.setToolTip(tip)
        self.b_sync.setText("◌ Analyzing…" if running else "⚡ Synchronize")
        self._refresh_summary()

    def _update_title(self) -> None:
        mark = "*" if self.state.dirty else ""
        self.setWindowTitle(f"{self.state.name}{mark} — {APP_NAME}")

    def _on_selection(self, media_id: str) -> None:
        self.inspector.show_media(media_id)
        m = self.state.get(media_id) if media_id else None
        self.bottom.selection.setText(f"{m.name} • {m.role}" if m else "Select a clip to inspect it")

    # ---- playback (audio, clip + reference) -----------------------------------------
    def toggle_play(self, *_args) -> None:
        if self.player.playing:
            self.player.stop()
            return
        tl, st = self.state.timeline, self.state
        mid = self.timeline.selected or self.library.selected_id()
        if tl is None or not st.sync_results:
            self.set_status("Synchronize first, then select a clip to play it")
            return
        clip = tl.clip_for(mid) if mid else None
        if clip is None:
            self.set_status("Select a clip on the timeline to play it")
            return
        m = st.get(mid)
        wav = SyncPlayer.wav_for(m)
        if wav is None:
            self.set_status("This clip has no prepared audio to play")
            return
        t = self.timeline.playhead
        if not (clip.start <= t < clip.end):
            t = float(clip.start)
        parts = [(wav, t - float(clip.start) + float(clip.source_in), float(clip.start - clip.source_in))]
        ref = next((x for x in st.media if x.is_master and x.id != mid), None)
        rclip = tl.clip_for(ref.id) if ref else None
        rwav = SyncPlayer.wav_for(ref) if ref else None
        if clip.synced and rclip is not None and rwav is not None and rclip.start <= t < rclip.end:
            parts.append((rwav, t - float(rclip.start) + float(rclip.source_in), float(rclip.start - rclip.source_in)))
        if not self.player.play(parts):
            self.set_status("Could not start playback")
            return
        self.bottom.b_play.setText("⏸")
        self.set_status("Playing " + (f"{m.name} with the reference" if len(parts) > 1 else m.name))

    def _on_play_position(self, t: float) -> None:
        self.timeline.jump_to(t)

    def _on_play_stopped(self) -> None:
        self.bottom.b_play.setText("▶")

    def export_timeline(self) -> None:
        from core.export.fcp7 import ExportError, export_xmeml
        tl = self.state.timeline
        if tl is None or not self.state.sync_results:
            QMessageBox.information(self, APP_NAME, "Synchronize first, then export.")
            return
        default = str(Path(self.config.last_media_dir or str(Path.home())) / f"{self.state.name or 'Anthem Sequence'}.xml")
        path, _ = QFileDialog.getSaveFileName(self, "Export Timeline (Premiere Pro XML)", default, "Final Cut Pro XML (*.xml)")
        if not path:
            return
        if not path.lower().endswith(".xml"):
            path += ".xml"
        try:
            xml, skipped = export_xmeml(tl, self.state.media, Path(path).stem)
            Path(path).write_text(xml, encoding="utf-8")
        except (ExportError, OSError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Export failed: {exc}")
            return
        note = f" {len(skipped)} unsynchronized clip(s) were left out." if skipped else ""
        self.set_status(f"Exported {Path(path).name}.{note} In Premiere: File → Import.")

    def _noop(self) -> None:  # only reachable if a pending action is enabled by mistake
        log.error("Triggered an unimplemented action")

    # ---- actions ------------------------------------------------------------
    def analyze(self) -> None:
        if self._sync_job is not None:
            return
        pending = [m for m in self.state.media if m.info is None and not m.error]
        if pending:
            self.set_status("Still inspecting media; try again in a moment")
            return
        master = self.state.auto_reference()
        if master is None:
            self.set_status("No clip with audio found to use as the reference")
            return
        inputs = []
        for m in self.state.media:
            idx = m.info.audio[0].index if (m.info is not None and m.info.audio) else None
            inputs.append(SyncInput(m.id, m.name, m.path, idx, _clock_hint(m)))
        job = make_sync_job(inputs, master.id, self.deps.ffmpeg, cache_dir() / "analysis")
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_synced)
        job.failed.connect(self._on_job_failed)
        job.cancelled.connect(self._on_job_cancelled)
        job.done.connect(self._on_job_done)
        self._sync_job = job
        self._jobs.append(job)
        self.progress.setValue(0)
        self._set_state("busy", "Analyzing")
        self.set_status(f"Comparing audio waveforms (reference: {master.name})…")
        self._refresh_actions()
        job.start()

    def _load_waveforms(self) -> None:
        items = [(m.id, m.path, m.info.audio[0].index) for m in self.state.media if m.info is not None and m.info.audio]
        if not items:
            return
        job = make_peaks_job(items, cache_dir() / "analysis")
        job.finished.connect(self.state.set_peaks)
        job.failed.connect(self._on_job_failed)
        job.done.connect(self._on_job_done)
        self._jobs.append(job)
        job.start()

    def cancel_analysis(self) -> None:
        if self._sync_job is not None:
            self._sync_job.cancel()
            self.set_status("Cancelling…")

    def _on_synced(self, results: dict) -> None:
        self.state.set_sync_results(results)
        self.inspector.show_results(results)
        self._load_waveforms()
        weak = sum(1 for r in results.values() if not r.usable)
        self.progress.setValue(100)
        self._restore_state()
        self.set_status("Tracks aligned. " + (f"{weak} clip(s) need manual review." if weak else "All clips synchronized."))

    # Worker signals are connected to these bound methods (not lambdas) so Qt delivers them on the UI thread.
    def _on_job_failed(self, msg: str) -> None:
        self._set_state("failed", "Failed")
        self.set_status(f"Failed: {msg}")

    def _on_job_cancelled(self) -> None:
        self._restore_state()
        self.set_status("Analysis cancelled")

    def _on_job_done(self) -> None:
        job = self.sender()                      # the Job that emitted `done`
        if job is self._sync_job:
            self._sync_job = None
        self._job_done(job)
        self._refresh_actions()

    def new_project(self) -> None:
        if self.state.dirty and QMessageBox.question(
                self, APP_NAME, "Discard unsaved changes and start a new project?") != QMessageBox.Yes:
            return
        self.state.reset()
        self.set_status("New project")

    def _pick(self, title: str, flt: str) -> list[str]:
        files, _ = QFileDialog.getOpenFileNames(self, title, self.config.last_media_dir, flt)
        if files:
            self.config.last_media_dir = str(Path(files[0]).parent)
        return files

    def _add(self, files: list[str], force: MediaKind | None) -> None:
        if not files:
            return
        added, rejected = self.state.add_files(files, force)
        msg = f"Added {len(added)} file(s)"
        if rejected:
            msg += f"; skipped {len(rejected)} (unsupported type, wrong kind, or already imported)"
            log.warning("Rejected files: %s", rejected)
        self.set_status(msg)
        self.probe(added)

    def probe(self, items) -> None:
        if not items:
            return
        if not self.deps.ffprobe:
            QMessageBox.warning(self, APP_NAME, "FFprobe was not found; media cannot be inspected.")
            return
        job = make_probe_job([(m.id, m.path) for m in items], self.deps.ffprobe)
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_probed)
        job.failed.connect(self._on_job_failed)
        job.done.connect(self._on_job_done)
        self._jobs.append(job)
        self._set_state("busy", "Inspecting")
        job.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.set_status(msg)

    def _on_probed(self, results: dict) -> None:
        from app.errors import MediaError
        bad = 0
        for mid, r in results.items():
            if isinstance(r, MediaError):
                bad += 1
                self.state.set_probe(mid, None, str(r))
            else:
                self.state.set_probe(mid, r)
        self.set_status(f"Probed {len(results)} file(s)" + (f", {bad} with problems (see Inspector)" if bad else ""))
        self.inspector.show_media(self.library.selected_id())
        if not self.state.sync_results:
            self.timeline.fit()

    def _job_done(self, job) -> None:
        job.wait()   # safe: runs on the UI thread, after the worker thread has been asked to quit
        if job in self._jobs:
            self._jobs.remove(job)
        if not self._jobs:
            if not self.state.sync_results:
                self.progress.setValue(0)
            self._restore_state()

    def import_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Import Folder", self.config.last_media_dir)
        if not d:
            return
        self.config.last_media_dir = d
        try:
            added, rejected, groups = self.state.add_folder(d)
        except OSError as exc:
            log.exception("Folder import failed")
            QMessageBox.warning(self, APP_NAME, f"Could not read folder:\n{exc}")
            return
        self.set_status(f"Imported {len(added)} file(s) in {len(groups)} group(s): {', '.join(groups)}"
                        + (f"; skipped {len(rejected)} duplicate(s)" if rejected else ""))
        self.probe(added)

    def import_media(self) -> None:
        self._add(self._pick("Import Media", f"{ALL_FILTER};;{VIDEO_FILTER};;{AUDIO_FILTER}"), None)

    def add_camera(self) -> None:
        self._add(self._pick("Add Camera", VIDEO_FILTER), MediaKind.VIDEO)

    def add_audio(self) -> None:
        self._add(self._pick("Add Audio", AUDIO_FILTER), MediaKind.AUDIO)

    def set_master(self) -> None:
        mid = self.library.selected_id()
        m = self.state.get(mid) if mid else None
        if m is None or not self.state.set_master(mid):
            QMessageBox.information(self, APP_NAME, "Select a clip or audio file that contains audio in the media library first.")
            return
        self.set_status(f"Reference: {m.name}")

    def closeEvent(self, ev: QCloseEvent) -> None:
        if self.state.dirty and not __import__("os").environ.get("AUTOSYNC_HEADLESS"):
            r = QMessageBox.question(self, APP_NAME, "You have unsaved changes. Quit anyway?")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
        for j in list(self._jobs):
            j.cancel(); j.wait()
        self.config.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        ev.accept()
