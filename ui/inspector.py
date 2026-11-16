"""Right panel: media inspector and synchronization results table."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QTableWidget, QTabWidget, QVBoxLayout, QWidget

from app.state import ProjectState
from ui.review import ReviewPanel

SYNC_COLUMNS = ["Source", "Offset (s)", "Confidence", "Corr.", "Windows", "Drift (ppm)", "Status"]


class Inspector(QTabWidget):
    def __init__(self, state: ProjectState) -> None:
        super().__init__()
        self.state = state
        info = QWidget()
        form = QFormLayout(info)
        self.fields = {k: QLabel("—") for k in ("Name", "Role", "Type", "Session", "Path", "Duration", "Video", "Audio", "Timecode")}
        for k, v in self.fields.items():
            v.setWordWrap(True)
            form.addRow(k, v)
        self.addTab(info, "Inspector")
        self.results = QTableWidget(0, len(SYNC_COLUMNS))
        self.results.setHorizontalHeaderLabels(SYNC_COLUMNS)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.horizontalHeader().setStretchLastSection(True)
        self.addTab(self.results, "Sync Results")
        self.review = ReviewPanel(state)
        self.addTab(self.review, "Review")

    def show_media(self, media_id: str) -> None:
        self.review.set_media(media_id)
        m = self.state.get(media_id) if media_id else None
        for v in self.fields.values():
            v.setText("—")
        if m is None:
            return
        self.fields["Name"].setText(m.name)
        self.fields["Role"].setText(m.role + (" (master)" if m.is_master else ""))
        self.fields["Type"].setText(m.kind.value)
        self.fields["Session"].setText(m.session)
        self.fields["Path"].setText(m.path + ("" if m.exists else "\n⚠ file missing"))
        if m.error:
            self.fields["Duration"].setText("⚠ " + m.error)
        elif m.info is not None:
            for k, v in m.info.summary().items():
                self.fields[k].setText(v)
            if m.info.warnings:
                self.fields["Duration"].setText(self.fields["Duration"].text() + "\n⚠ " + "\n⚠ ".join(m.info.warnings))
        else:
            self.fields["Duration"].setText("probing…")

    def show_results(self, results: dict) -> None:
        """Fill the Sync Results table. `results` maps media id -> SyncResult."""
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QTableWidgetItem
        colors = {"High": "#3fb37f", "Medium": "#e8913a", "Manual": "#39c6ec", "Low": "#d9534f", "Failed": "#d9534f"}
        self.results.setRowCount(0)
        for mid, r in results.items():
            m = self.state.get(mid)
            if m is None:
                continue
            status = "Reference" if r.method == "reference" else ("Confirmed" if r.confirmed else ("Synced" if r.usable else "Needs review"))
            row = self.results.rowCount()
            self.results.insertRow(row)
            vals = [m.role, f"{r.offset:+.4f}", r.confidence, f"{r.correlation:.2f}",
                    f"{r.windows_verified}/{r.windows_total}", f"{r.drift_ppm:+.1f}", status]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QColor(colors.get(r.confidence, "#d8dce0")))
                if r.notes:
                    it.setToolTip("\n".join(r.notes))
                self.results.setItem(row, c, it)
        self.setCurrentIndex(1)
