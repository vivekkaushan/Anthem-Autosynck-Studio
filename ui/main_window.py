"""Main application window: toolbar, library, workspace, inspector, status area."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QToolButton,
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
from ui.media_library import MediaLibrary
from ui.timeline_view import TimelinePanel, fmt_time
from workers.update_worker import make_update_job
from workers.waveform_worker import make_peaks_job
from app import __version__

log = logging.getLogger(__name__)

VIDEO_FILTER = "Video (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTS)) + ")"
AUDIO_FILTER = "Audio (" + " ".join(f"*{e}" for e in sorted(AUDIO_EXTS)) + ")"
ALL_FILTER = "Media (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTS | AUDIO_EXTS)) + ")"


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
        self.a_master = A("Set Master Audio", self.set_master, "Use the selected audio file as the sync reference")
        self.a_sync = A("⚡ Synchronize", self.analyze, "Analyze and synchronize all recordings to the master audio")
        self.a_cancel = A("Cancel", self.cancel_analysis, "Cancel the running analysis")
        self.a_updates = A("Check for Updates…", self.check_updates_now, "Look for a newer version on GitHub")
        self.a_auto_updates = A("Check for updates at startup", self._toggle_auto_updates,
                                "Contact GitHub once at startup to see whether a newer version exists (nothing else is sent)")
        self.a_auto_updates.setCheckable(True)
        self.a_auto_updates.setChecked(self.config.check_updates)
        self.a_export = A("Export Timeline ↗", self._noop, "Export FCP7 XML for Premiere Pro", pending="XML export, Phase 8")

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
        if tl is None:
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
        s.t_dur.set_value(fmt_time(float(tl.duration)) if tl is not None else "—")
        if self._sync_job is not None:
            chip = "ANALYZING"
        elif tl is not None:
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
        if self._update_info is not None:
            QDesktopServices.openUrl(QUrl(self._update_info.download_url))
            self.set_status(f"Downloading version {self._update_info.version} in your browser. Open it when it finishes.")

    def _help(self) -> None:
        QMessageBox.information(self, APP_NAME, "1. Add Media → Import Folder (Camera 1, Camera 2, Audio 1…)\n"
                                "2. Select your recorder's audio, then Add Media → Set Master Audio\n"
                                "3. Synchronize, then check the confidence of each clip\n"
                                "4. Export Timeline (Premiere XML) arrives in a later release")

    # ---- state-driven UI --------------------------------------------------
    def _refresh_actions(self) -> None:
        # Actions marked "pending" stay disabled until their phase is implemented.
        has_audio = any(m.kind is MediaKind.AUDIO for m in self.state.media)
        self.a_master.setEnabled(has_audio)
        running = self._sync_job is not None
        master = next((m for m in self.state.media if m.is_master), None)
        others = [m for m in self.state.media if not m.is_master]
        self.a_sync.setEnabled(not running and master is not None and bool(others))
        self.a_cancel.setEnabled(running)
        self.b_cancel.setVisible(running)
        tip = "Analyze and synchronize all recordings to the master audio"
        if master is None:
            tip += "\n(Set a master audio file first)"
        elif not others:
            tip += "\n(Add at least one camera or second audio file)"
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
        inputs = []
        for m in self.state.media:
            idx = m.info.audio[0].index if (m.info is not None and m.info.audio) else None
            inputs.append(SyncInput(m.id, m.name, m.path, idx))
        master = next(m for m in self.state.media if m.is_master)
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
        self.set_status("Comparing audio waveforms across recordings…")
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

    def _job_done(self, job) -> None:
        job.wait()   # safe: runs on the UI thread, after the worker thread has been asked to quit
        if job in self._jobs:
            self._jobs.remove(job)
        if not self._jobs:
            if self.state.timeline is None:
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
        if m is None or m.kind is not MediaKind.AUDIO:
            QMessageBox.information(self, APP_NAME, "Select an audio file in the media library first.")
            return
        self.state.set_master(mid)
        self.set_status(f"Master audio: {m.name}")

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
