"""Main application window: toolbar, library, workspace, inspector, status area."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox, QProgressBar, QSplitter,
                               QToolBar, QToolButton, QWidget)

from app import APP_NAME
from app.config import Config
from app.dependencies import DependencyReport
from app.state import ProjectState
from core.media.models import AUDIO_EXTS, VIDEO_EXTS, MediaKind
from workers.probe_worker import make_probe_job
from workers.sync_worker import make_sync_job
from core.synchronization.engine import SyncInput
from app.paths import cache_dir
from ui.inspector import Inspector
from ui.media_library import MediaLibrary
from ui.timeline_view import TimelinePanel
from workers.waveform_worker import make_peaks_job

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
        self.setMinimumSize(1000, 640)
        self.resize(1440, 860)

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
        self.hsplit.setSizes([300, 760, 340])
        self.hsplit.setChildrenCollapsible(False)
        self.setCentralWidget(self.hsplit)

        self._build_toolbar()
        self._build_status()
        self._refresh_actions()
        self.state.changed.connect(self._refresh_actions)
        self.state.changed.connect(self._update_title)
        self._update_title()
        if config.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(config.window_geometry.encode()))

    # ---- toolbar --------------------------------------------------------
    def _act(self, bar: QToolBar, text: str, slot, tip: str, *, primary=False, danger=False, pending: str = "") -> QAction:
        a = QAction(text.replace("&", "&&"), self)  # escape Qt mnemonic marker
        a.setToolTip(tip if not pending else f"{tip}\n(Not available yet: {pending})")
        a.triggered.connect(slot)
        bar.addAction(a)
        btn = bar.widgetForAction(a)
        if isinstance(btn, QToolButton):
            btn.setObjectName("primary" if primary else ("danger" if danger else ""))
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        a.setProperty("pending", pending)
        if pending:
            a.setEnabled(False)
        return a

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(bar)
        A = self._act
        self.a_new = A(bar, "New Project", self.new_project, "Start an empty project")
        self.a_open = A(bar, "Open Project", self._noop, "Open a saved project", pending="project database, Phase 9")
        self.a_save = A(bar, "Save Project", self._noop, "Save the project", pending="project database, Phase 9")
        bar.addSeparator()
        self.a_import = A(bar, "Import Media", self.import_media, "Import video and audio files")
        self.a_folder = A(bar, "Import Folder", self.import_folder, "Import a folder; each sub-folder (Camera 1, Camera 2…) becomes one group and track")
        self.a_cam = A(bar, "Add Camera", self.add_camera, "Add camera video recordings")
        self.a_aud = A(bar, "Add Audio", self.add_audio, "Add external audio recordings")
        self.a_master = A(bar, "Set Master Audio", self.set_master, "Use the selected audio file as the sync reference")
        bar.addSeparator()
        self.a_sync = A(bar, "Analyze & Sync", self.analyze, "Analyze and synchronize all recordings to the master audio", primary=True)
        self.a_cancel = A(bar, "Cancel Analysis", self.cancel_analysis, "Cancel the running analysis", danger=True)
        bar.addSeparator()
        self.a_manual = A(bar, "Manual Offset", self._noop, "Adjust offset of the selected clip", pending="manual correction, Phase 7")
        self.a_preview = A(bar, "Preview Sync", self._noop, "Review synchronized positions", pending="sync review, Phase 7")
        bar.addSeparator()
        self.a_export = A(bar, "Export Premiere XML", self._noop, "Export FCP7 XML for Premiere Pro", primary=True, pending="XML export, Phase 8")
        self._actions = [self.a_new, self.a_open, self.a_save, self.a_import, self.a_folder, self.a_cam, self.a_aud, self.a_master,
                         self.a_sync, self.a_cancel, self.a_manual, self.a_preview, self.a_export]

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.status_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.dep_label = QLabel()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.dep_label)
        if self.deps.ok:
            self.dep_label.setText(f"FFmpeg {self.deps.ffmpeg_version}")
        else:
            self.dep_label.setText("⚠ dependencies missing")
            self.dep_label.setStyleSheet("color:#e8913a")
            self.dep_label.setToolTip("\n".join(self.deps.problems()))

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # ---- state-driven UI --------------------------------------------------
    def _refresh_actions(self) -> None:
        # Actions marked "pending" stay disabled until their phase is implemented.
        has_audio = any(m.kind is MediaKind.AUDIO for m in self.state.media)
        self.a_master.setEnabled(has_audio)
        self.a_import.setEnabled(True)
        running = self._sync_job is not None
        master = next((m for m in self.state.media if m.is_master), None)
        others = [m for m in self.state.media if not m.is_master]
        self.a_sync.setEnabled(not running and master is not None and bool(others))
        self.a_cancel.setEnabled(running)
        tip = "Analyze and synchronize all recordings to the master audio"
        if master is None:
            tip += "\n(Set a master audio file first)"
        elif not others:
            tip += "\n(Add at least one camera or second audio file)"
        self.a_sync.setToolTip(tip)

    def _update_title(self) -> None:
        mark = "*" if self.state.dirty else ""
        self.setWindowTitle(f"{self.state.name}{mark} — {APP_NAME}")

    def _on_selection(self, media_id: str) -> None:
        self.inspector.show_media(media_id)

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
        self.progress.setVisible(True)
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
        self.set_status("Synchronization complete" + (f"; {weak} result(s) need review" if weak else ""))

    # Worker signals are connected to these bound methods (not lambdas) so Qt delivers them on the UI thread.
    def _on_job_failed(self, msg: str) -> None:
        self.set_status(f"Failed: {msg}")

    def _on_job_cancelled(self) -> None:
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
        self.progress.setVisible(True)
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
            self.progress.setVisible(False)

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
