"""Central workspace: zoomable multi-track timeline with waveform clips and a sync status bar."""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollBar, QVBoxLayout, QWidget

from app.state import ProjectState
from core.media.models import MediaKind
from core.media.waveform import PEAKS_PER_SEC
from ui import theme

HEADER_W = 200
RULER_H = 34
LANE_H = 65
STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]


def fmt_time(t: float, fine: bool = False) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    base = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
    return base + (f".{int((s % 1) * 100):02d}" if fine else "")


class TimelineView(QWidget):
    clip_selected = Signal(str)       # media id
    playhead_changed = Signal(float)  # seconds on timeline
    view_changed = Signal()

    def __init__(self, state: ProjectState) -> None:
        super().__init__()
        self.state = state
        self.px_per_sec = 12.0
        self.scroll = 0.0            # seconds at the left edge of the clip area
        self.playhead = 0.0
        self.selected = ""
        self.setMinimumHeight(180)
        self.setMouseTracking(False)
        state.media_changed.connect(self.update)
        state.timeline_changed.connect(self._on_timeline)

    # ---- model helpers --------------------------------------------------------
    def lane_info(self) -> list[tuple[str, str, int]]:
        """(track label, title, clip count). Uses the timeline once synced; otherwise derives lanes from imported media."""
        if self.state.timeline is not None:
            return [(t.label, t.title, len(t.clips)) for t in self.state.timeline.tracks]

        def uniq(items):
            seen, out = set(), []
            for m in items:           # one lane per role: all clips of a camera share its track
                if m.role not in seen:
                    seen.add(m.role)
                    out.append(m)
            return out
        count = {}
        for m in self.state.media:
            count[m.role] = count.get(m.role, 0) + 1
        cams = uniq(m for m in self.state.media if m.kind is MediaKind.VIDEO)
        auds = uniq(sorted((m for m in self.state.media if m.kind is MediaKind.AUDIO), key=lambda m: not m.is_master))
        lanes = [(f"V{i}", m.role, count.get(m.role, 0)) for i, m in enumerate(cams, 1)]
        lanes += [(f"A{i}", ("Master Audio" if m.is_master else m.role), count.get(m.role, 0)) for i, m in enumerate(auds, 1)]
        return lanes

    def lanes(self) -> list[tuple[str, str]]:
        return [(a, b) for a, b, _ in self.lane_info()]

    def total_seconds(self) -> float:
        tl = self.state.timeline
        return float(tl.duration) if tl else 0.0

    def _on_timeline(self) -> None:
        self.update()
        self.view_changed.emit()

    # ---- view transforms --------------------------------------------------------
    def _x(self, t: float) -> float:
        return HEADER_W + (t - self.scroll) * self.px_per_sec

    def _t(self, x: float) -> float:
        return (x - HEADER_W) / self.px_per_sec + self.scroll

    def visible_seconds(self) -> float:
        return max(1.0, (self.width() - HEADER_W) / self.px_per_sec)

    def set_scroll(self, seconds: float) -> None:
        self.scroll = max(0.0, seconds)
        self.update()

    def zoom(self, factor: float, anchor_x: float | None = None) -> None:
        ax = HEADER_W + (self.width() - HEADER_W) / 2 if anchor_x is None else anchor_x
        t_anchor = self._t(ax)
        self.px_per_sec = float(np.clip(self.px_per_sec * factor, 0.05, 2000.0))
        self.scroll = max(0.0, t_anchor - (ax - HEADER_W) / self.px_per_sec)
        self.update()
        self.view_changed.emit()

    def fit(self) -> None:
        total = self.total_seconds()
        if total > 0:
            self.px_per_sec = max(0.05, (self.width() - HEADER_W - 20) / total)
            self.scroll = 0.0
            self.update()
            self.view_changed.emit()

    # ---- interaction ----------------------------------------------------------------
    def wheelEvent(self, ev) -> None:
        if ev.modifiers() & Qt.ControlModifier:
            self.zoom(1.25 if ev.angleDelta().y() > 0 else 0.8, ev.position().x())
        else:
            d = ev.angleDelta().x() or ev.angleDelta().y()
            self.set_scroll(self.scroll - d / 120.0 * 60.0 / self.px_per_sec)
            self.view_changed.emit()
        ev.accept()

    def mousePressEvent(self, ev) -> None:
        x, y = ev.position().x(), ev.position().y()
        if x < HEADER_W:
            return
        if y <= RULER_H:
            self._set_playhead(self._t(x))
            return
        tl = self.state.timeline
        if tl is None:
            return
        lane = int((y - RULER_H) // LANE_H)
        t = self._t(x)
        if 0 <= lane < len(tl.tracks):
            for c in tl.tracks[lane].clips:
                if float(c.start) <= t <= float(c.end):
                    self.selected = c.media_id
                    self.clip_selected.emit(c.media_id)
                    break
            else:
                self.selected = ""
            self._set_playhead(t)
            self.update()

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() & Qt.LeftButton and ev.position().y() <= RULER_H:
            self._set_playhead(self._t(ev.position().x()))

    def jump_to(self, t: float) -> None:
        """Move the playhead and scroll so it is visible."""
        self._set_playhead(t)
        if not (self.scroll <= t <= self.scroll + self.visible_seconds()):
            self.scroll = max(0.0, t - self.visible_seconds() * 0.1)
        self.update()
        self.view_changed.emit()

    def _set_playhead(self, t: float) -> None:
        self.playhead = max(0.0, t)
        self.playhead_changed.emit(self.playhead)
        self.update()

    # ---- painting ------------------------------------------------------------------------
    def _draw_ruler(self, p: QPainter) -> None:
        p.fillRect(0, 0, self.width(), RULER_H, QColor("#16202d"))
        step = next((s for s in STEPS if s * self.px_per_sec >= 90), STEPS[-1])
        t = math.floor(self.scroll / step) * step
        f = QFont(self.font()); f.setPointSize(8); p.setFont(f)
        while self._x(t) < self.width():
            x = self._x(t)
            if x >= HEADER_W:
                p.setPen(QPen(QColor("#334354")))
                p.drawLine(QPointF(x, RULER_H - 12), QPointF(x, RULER_H))
                p.setPen(QPen(QColor("#97a7b7")))
                p.drawText(QRectF(x + 4, 0, 90, RULER_H - 8), Qt.AlignVCenter | Qt.AlignLeft, fmt_time(t, step < 1))
            sub = step / 5
            p.setPen(QPen(QColor("#2a394b")))
            for k in range(1, 5):
                xs = self._x(t + sub * k)
                if xs >= HEADER_W and xs < self.width():
                    p.drawLine(QPointF(xs, RULER_H - 5), QPointF(xs, RULER_H))
            t += step

    def _draw_grid(self, p: QPainter, y: float) -> None:
        step = next((s for s in STEPS if s * self.px_per_sec >= 90), STEPS[-1])
        t = math.floor(self.scroll / step) * step
        p.setPen(QPen(QColor("#1d2a3a")))
        while self._x(t) < self.width():
            x = self._x(t)
            if x >= HEADER_W:
                p.drawLine(QPointF(x, y), QPointF(x, y + LANE_H))
            t += step

    def _draw_wave(self, p: QPainter, peaks: np.ndarray, c, rect: QRectF, color: QColor) -> None:
        """Draw min/max columns for the visible part of one clip."""
        x0 = max(rect.left(), HEADER_W)
        x1 = min(rect.right(), float(self.width()))
        if x1 <= x0 or len(peaks) == 0:
            return
        cols = np.arange(int(x0), int(math.ceil(x1)))
        t0 = (self._t(cols.astype(float)) - float(c.start) + float(c.source_in)) * PEAKS_PER_SEC
        t1 = t0 + PEAKS_PER_SEC / self.px_per_sec
        i0 = np.clip(np.floor(t0).astype(int), 0, len(peaks) - 1)
        i1 = np.clip(np.maximum(np.ceil(t1).astype(int), i0 + 1), 1, len(peaks))
        valid = i0 < i1
        if not valid.any():
            return
        cols, i0, i1 = cols[valid], i0[valid], i1[valid]
        # reduceat over interleaved [start, end) boundaries gives min/max per pixel column without a Python loop.
        # A sentinel element lets the final boundary equal len(peaks) (reduceat indices must be < len).
        n = len(peaks)
        idx = np.empty(len(i0) * 2, dtype=int)
        idx[0::2], idx[1::2] = i0, np.minimum(i1, n)
        lo = np.append(peaks[:, 0], 0.0)
        hi = np.append(peaks[:, 1], 0.0)
        mins = np.minimum.reduceat(lo, idx)[0::2]
        maxs = np.maximum.reduceat(hi, idx)[0::2]
        mid = rect.center().y()
        amp = (rect.height() / 2 - 3)
        lines = [QLineF(float(x), mid - float(mx) * amp * 1.9, float(x), mid - float(mn) * amp * 1.9)
                 for x, mn, mx in zip(cols, mins, maxs)]
        p.setPen(QPen(color, 1))
        p.drawLines(lines)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#0f1721"))
        info = self.lane_info()
        tl = self.state.timeline
        y = RULER_H
        if not info:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(HEADER_W, RULER_H, self.width() - HEADER_W, self.height() - RULER_H), Qt.AlignCenter,
                       "Import cameras and external audio, set the master audio, then Synchronize")
        font = QFont(self.font()); font.setPointSize(9)
        title_font = QFont(self.font()); title_font.setPointSize(10); title_font.setBold(True)
        meta_font = QFont(self.font()); meta_font.setPointSize(8)
        for li, (label, title, n) in enumerate(info):
            is_video = label.startswith("V")
            lane_rect = QRectF(HEADER_W, y, self.width() - HEADER_W, LANE_H)
            p.fillRect(lane_rect, QColor("#101924" if li % 2 == 0 else "#131d29"))
            self._draw_grid(p, y)
            if tl is not None and li < len(tl.tracks):
                self._draw_track(p, tl.tracks[li], y, is_video, font)
            # track header
            p.fillRect(QRectF(0, y, HEADER_W, LANE_H), QColor("#101924" if li % 2 == 0 else "#131d29"))
            box = QRectF(13, y + (LANE_H - 35) / 2, 35, 35)
            path = QPainterPath(); path.addRoundedRect(box, 9, 9)
            p.setPen(QPen(QColor("#365267" if is_video else "#5b4a30"), 1)); p.setBrush(QBrush(QColor("#203347" if is_video else "#2e2a22")))
            p.drawPath(path)
            p.setFont(font)
            p.setPen(QColor("#8adff3" if is_video else theme.ORANGE))
            p.drawText(box, Qt.AlignCenter, label)
            p.setFont(title_font); p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(58, y + 14, HEADER_W - 64, 18), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(title, Qt.ElideRight, int(HEADER_W - 66)))
            p.setFont(meta_font); p.setPen(QColor("#8c9db0"))
            p.drawText(QRectF(58, y + 33, HEADER_W - 64, 16), Qt.AlignVCenter | Qt.AlignLeft, f"{n} clip" + ("" if n == 1 else "s"))
            y += LANE_H
            p.setPen(QPen(QColor("#2c3a4a")))
            p.drawLine(0, int(y), self.width(), int(y))
        self._draw_ruler(p)
        p.setPen(QPen(QColor("#354256")))
        p.drawLine(0, RULER_H, self.width(), RULER_H)
        p.setPen(QPen(QColor("#39485c")))
        p.drawLine(HEADER_W, 0, HEADER_W, self.height())
        p.setPen(QColor("#93a9bf")); f = QFont(self.font()); f.setPointSize(8); p.setFont(f)
        p.drawText(QRectF(17, 0, HEADER_W - 20, RULER_H), Qt.AlignVCenter | Qt.AlignLeft, "SOURCE TRACKS")
        # playhead
        px = self._x(self.playhead)
        if HEADER_W <= px <= self.width():
            p.setPen(QPen(QColor("#f8b857"), 2))
            p.drawLine(QPointF(px, 0), QPointF(px, self.height()))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor("#f8b857")))
            p.drawPolygon(QPolygonF([QPointF(px - 6, 0), QPointF(px + 6, 0), QPointF(px, 9)]))

    def _draw_track(self, p: QPainter, track, y: float, is_video: bool, font: QFont) -> None:
        p.save()
        p.setClipRect(QRectF(HEADER_W, y, self.width() - HEADER_W, LANE_H))
        p.setRenderHint(QPainter.Antialiasing, True)
        for c in track.clips:
            x0, x1 = self._x(float(c.start)), self._x(float(c.end))
            if x1 < HEADER_W or x0 > self.width():
                continue
            rect = QRectF(x0, y + 10, max(2.0, x1 - x0), LANE_H - 20)
            bad = not c.synced
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if bad:
                g.setColorAt(0, QColor("#ab5961")); g.setColorAt(1, QColor("#843f4c"))
            elif is_video:
                g.setColorAt(0, QColor("#2488a6")); g.setColorAt(1, QColor("#1a627f"))
            else:
                g.setColorAt(0, QColor("#267c94")); g.setColorAt(1, QColor("#165b75"))
            path = QPainterPath(); path.addRoundedRect(rect, 4, 4)
            p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawPath(path)
            p.setRenderHint(QPainter.Antialiasing, False)
            pk = self.state.peaks.get(c.media_id)
            if pk is not None:
                self._draw_wave(p, pk, c, rect.adjusted(0, 12, 0, 0), QColor("#ffc9cc") if bad else QColor("#8beaff"))
            p.setRenderHint(QPainter.Antialiasing, True)
            sel = c.media_id == self.selected
            pen = QPen(QColor("#d1f6ff") if sel else QColor("#e37a82" if bad else "#41b2cc"), 2 if sel else 1)
            if bad:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(path)
            if rect.width() > 40:
                f = QFont(font); f.setPointSize(8); p.setFont(f)
                p.setPen(QColor("#ffe1e3" if bad else "#b7efff"))
                p.drawText(rect.adjusted(6, 4, -3, 0), Qt.AlignTop | Qt.AlignLeft, c.name + ("  ⚠ not synced" if bad else ""))
            if c.confidence in ("Medium", "Low") and not bad:     # review marker
                p.setBrush(QBrush(QColor(theme.ORANGE))); p.setPen(Qt.NoPen)
                p.drawPolygon(QPolygonF([QPointF(rect.right() - 11, rect.top() + 1), QPointF(rect.right() - 1, rect.top() + 1), QPointF(rect.right() - 1, rect.top() + 11)]))
        p.restore()


class TimelinePanel(QWidget):
    """Timeline toolbar + TimelineView + horizontal scrollbar + 'N/M clips synchronized' bar."""

    def __init__(self, state: ProjectState) -> None:
        super().__init__()
        self.state = state
        self.view = TimelineView(state)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        barw = QFrame(); barw.setObjectName("timelinebar")
        bar = QHBoxLayout(barw)
        bar.setContentsMargins(24, 9, 20, 9)
        bar.setSpacing(12)
        head = QLabel("Synchronization Timeline"); head.setStyleSheet("font-size:13px; font-weight:700; background:transparent;")
        self.count_label = QLabel("0 tracks"); self.count_label.setObjectName("count")
        self.time_label = QLabel("00:00:00.00"); self.time_label.setStyleSheet("color:#8393a7; background:transparent;")
        bar.addWidget(head); bar.addWidget(self.count_label); bar.addStretch(1); bar.addWidget(self.time_label)
        for text, tip, fn in (("−", "Zoom out", lambda: self.view.zoom(0.7)), ("＋", "Zoom in", lambda: self.view.zoom(1.43)),
                              ("Fit", "Fit whole timeline", self.view.fit)):
            b = QPushButton(text); b.setObjectName("tool"); b.setToolTip(tip); b.clicked.connect(fn)
            bar.addWidget(b)
        lay.addWidget(barw)
        lay.addWidget(self.view, 1)
        self.sb = QScrollBar(Qt.Horizontal)
        self.sb.valueChanged.connect(lambda v: self.view.set_scroll(v / 100.0))
        lay.addWidget(self.sb)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setFixedHeight(28)
        lay.addWidget(self.status)
        self.view.view_changed.connect(self._sync_scrollbar)
        self.view.playhead_changed.connect(lambda t: self.time_label.setText(fmt_time(t, True)))
        state.timeline_changed.connect(self.update_status)
        state.timeline_changed.connect(self._sync_scrollbar)
        state.media_changed.connect(self._update_count)
        state.timeline_changed.connect(self._update_count)
        self.update_status()
        self._update_count()

    def _update_count(self) -> None:
        n = len(self.view.lane_info())
        self.count_label.setText(f"{n} track" + ("" if n == 1 else "s"))

    def _sync_scrollbar(self) -> None:
        total = self.view.total_seconds()
        page = self.view.visible_seconds()
        self.sb.blockSignals(True)
        self.sb.setRange(0, int(max(0.0, total - page) * 100))
        self.sb.setPageStep(int(page * 100))
        self.sb.setValue(int(self.view.scroll * 100))
        self.sb.blockSignals(False)

    def update_status(self) -> None:
        tl = self.state.timeline
        if tl is None:
            text, bg, fg, edge = "Not analyzed yet", "#131d2a", "#8393a7", "#263344"
        else:
            ok, total = tl.counts
            text = f"{ok}/{total} Clips Synchronized" + ("" if ok == total else f"  ·  {total - ok} need review")
            bg, fg, edge = (("#163d34", "#91f3cf", "#327a66") if ok == total else ("#40290f", "#ffca83", "#8a5a1f"))
        self.status.setText(text)
        self.status.setStyleSheet(f"background:{bg}; color:{fg}; font-weight:600; border-top:1px solid {edge};")
