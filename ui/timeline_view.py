"""Central workspace: track-lane canvas (V1..Vn, A1..An) with a time ruler.

Phase 2 draws the lane structure from project media; clips and waveforms are added
when the timeline engine (Phase 6) exists.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.state import ProjectState
from core.media.models import MediaKind
from ui import theme

HEADER_W = 150
RULER_H = 26
LANE_H = 44


class TimelineView(QWidget):
    def __init__(self, state: ProjectState) -> None:
        super().__init__()
        self.state = state
        self.setMinimumHeight(180)
        state.media_changed.connect(self.update)

    def lanes(self) -> list[tuple[str, str]]:
        """(track label, source name) – V1.. per camera, A1 master then other audio."""
        def uniq(items):
            seen, out = set(), []
            for m in items:           # one lane per role: all clips of a camera share its track
                if m.role not in seen:
                    seen.add(m.role)
                    out.append(m)
            return out
        cams = uniq(m for m in self.state.media if m.kind is MediaKind.VIDEO)
        auds = uniq(sorted((m for m in self.state.media if m.kind is MediaKind.AUDIO), key=lambda m: not m.is_master))
        lanes = [(f"V{i}", m.role) for i, m in enumerate(cams, 1)]
        lanes += [(f"A{i}", ("Master Audio" if m.is_master else m.role)) for i, m in enumerate(auds, 1)]
        return lanes

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.fillRect(0, 0, self.width(), RULER_H, QColor(theme.PANEL))
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawLine(0, RULER_H, self.width(), RULER_H)
        p.drawLine(HEADER_W, 0, HEADER_W, self.height())
        lanes = self.lanes()
        font = QFont(self.font()); font.setPointSize(9); p.setFont(font)
        if not lanes:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(HEADER_W, RULER_H, self.width() - HEADER_W, self.height() - RULER_H), Qt.AlignCenter,
                       "Import cameras and external audio to build the synchronized timeline")
            return
        y = RULER_H
        for label, src in lanes:
            is_video = label.startswith("V")
            rect = QRectF(0, y, HEADER_W, LANE_H)
            p.fillRect(rect, QColor(theme.PANEL_ALT))
            p.setPen(QColor(theme.TEAL if is_video else theme.ORANGE))
            p.drawText(rect.adjusted(8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, f"{label}  ")
            p.setPen(QColor(theme.TEXT))
            p.drawText(rect.adjusted(40, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, src)
            p.setPen(QPen(QColor(theme.BORDER)))
            y += LANE_H
            p.drawLine(0, y, self.width(), y)
