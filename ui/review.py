"""Review tab: check, nudge or accept the sync of the selected clip."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.state import ProjectState


class ReviewPanel(QWidget):
    listen_requested = Signal(str)

    def __init__(self, state: ProjectState) -> None:
        super().__init__()
        self.state = state
        self.media_id = ""
        lay = QVBoxLayout(self)
        self.title = QLabel("Select a clip to review its synchronization")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight:700; font-size:13px;")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8393a7;")
        lay.addWidget(self.title)
        lay.addWidget(self.status)

        self.b_listen = QPushButton("▶  Listen (clip + reference)")
        self.b_listen.setObjectName("primary")
        self.b_listen.setToolTip("Plays this clip together with the reference. Correct sync sounds like one voice; an echo means it is off.")
        self.b_listen.clicked.connect(lambda: self.listen_requested.emit(self.media_id))
        lay.addWidget(self.b_listen)

        grid = QGridLayout()
        grid.addWidget(QLabel("Offset (seconds)"), 0, 0)
        self.offset = QDoubleSpinBox()
        self.offset.setDecimals(4)
        self.offset.setRange(-1_000_000, 1_000_000)
        self.offset.setSingleStep(0.02)
        grid.addWidget(self.offset, 0, 1, 1, 4)
        self.nudges = []
        for col, (label, delta) in enumerate((("−1 s", -1.0), ("−1 frame", None), ("+1 frame", None), ("+1 s", 1.0))):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, d=delta, lb=label: self._nudge(d, lb))
            grid.addWidget(b, 1, col)
            self.nudges.append(b)
        lay.addLayout(grid)
        row = QHBoxLayout()
        self.b_apply = QPushButton("Apply offset")
        self.b_apply.setToolTip("Place the clip at this offset (marked Manual)")
        self.b_apply.clicked.connect(self._apply)
        self.b_accept = QPushButton("Accept match")
        self.b_accept.setToolTip("Accept the detected (Low confidence) match after you have checked it")
        self.b_accept.clicked.connect(self._accept)
        row.addWidget(self.b_apply)
        row.addWidget(self.b_accept)
        lay.addLayout(row)
        self.hint = QLabel("Offset = where the clip's start sits on the reference timeline.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#8393a7; font-size:11px;")
        lay.addWidget(self.hint)
        lay.addStretch(1)
        state.results_edited.connect(self.refresh)
        self.set_media("")

    def _frame(self) -> float:
        for m in self.state.media:
            v = getattr(m.info, "primary_video", None)
            if v is not None:
                return float(1 / v.frame_rate)
        return 0.04

    def set_media(self, media_id: str) -> None:
        self.media_id = media_id
        self.refresh()

    def refresh(self) -> None:
        m = self.state.get(self.media_id) if self.media_id else None
        r = self.state.sync_results.get(self.media_id) if m else None
        ok = m is not None and not m.is_master and bool(self.state.sync_results)
        for w in (self.offset, self.b_apply, *self.nudges):
            w.setEnabled(ok)
        self.b_listen.setEnabled(m is not None and bool(self.state.sync_results))
        self.b_accept.setEnabled(r is not None and r.confidence == "Low" and not r.confirmed)
        self.offset.setSingleStep(self._frame())
        if m is None:
            self.title.setText("Select a clip to review its synchronization")
            self.status.setText("")
            return
        self.title.setText(f"{m.name}  ·  {m.role}")
        if not self.state.sync_results:
            self.status.setText("Click Synchronize first.")
            return
        if m.is_master:
            self.status.setText("This is the reference. Everything else is aligned to it.")
            return
        if r is None:
            self.status.setText("Not analyzed.")
            return
        self.offset.blockSignals(True)
        self.offset.setValue(r.offset)
        self.offset.blockSignals(False)
        state = "placed" if r.usable else "NOT placed (needs review)"
        self.status.setText(f"{r.confidence} confidence · {state}\n" + "\n".join(r.notes[-2:]))

    def _nudge(self, delta, label: str) -> None:
        d = delta if delta is not None else (-self._frame() if label.startswith("−") else self._frame())
        self.offset.setValue(self.offset.value() + d)
        self._apply()

    def _apply(self) -> None:
        if self.media_id:
            self.state.set_manual_offset(self.media_id, round(self.offset.value(), 4))

    def _accept(self) -> None:
        if self.media_id:
            self.state.accept_match(self.media_id)
