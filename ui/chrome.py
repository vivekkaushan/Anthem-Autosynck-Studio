"""Window chrome: icon rail, top bar, summary tiles and the transport / status panel."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget)

from app.paths import resource_root


def _res(name: str):
    return resource_root() / "resources" / name


def logo_pixmap(size: int, tile: bool = True) -> QPixmap:
    """Anthem 'a' mark. With tile=True it sits on a white rounded square so it reads on the dark UI."""
    src = QPixmap(str(_res("anthem_logo.png")))
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    if tile:
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("white")))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
        inner = size * 0.62
        p.drawPixmap(QRectF((size - inner) / 2, (size - inner) / 2, inner, inner), src, QRectF(src.rect()))
    elif not src.isNull():
        p.drawPixmap(QRectF(0, 0, size, size), src, QRectF(src.rect()))
    p.end()
    return out


def app_icon() -> QIcon:
    path = _res("anthem_app_icon.png")
    return QIcon(str(path)) if path.is_file() else QIcon()


class Rail(QFrame):
    library_toggled = Signal(bool)
    inspector_toggled = Signal(bool)
    help_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("rail")
        self.setFixedWidth(68)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 17, 0, 16)
        lay.setSpacing(13)
        lay.setAlignment(Qt.AlignHCenter)
        brand = QLabel()
        brand.setPixmap(logo_pixmap(76))
        brand.setFixedSize(38, 38)
        brand.setScaledContents(True)
        brand.setToolTip("Anthem")
        brand.setStyleSheet("background: transparent;")
        lay.addWidget(brand, 0, Qt.AlignHCenter)
        lay.addSpacing(8)
        self.b_timeline = self._btn("▥", "Timeline", checked=True, checkable=False)
        self.b_library = self._btn("▤", "Show / hide the media library", checked=True)
        self.b_inspector = self._btn("◨", "Show / hide the inspector and sync results", checked=True)
        self.b_library.toggled.connect(self.library_toggled)
        self.b_inspector.toggled.connect(self.inspector_toggled)
        for b in (self.b_timeline, self.b_library, self.b_inspector):
            lay.addWidget(b, 0, Qt.AlignHCenter)
        lay.addStretch(1)
        self.b_help = self._btn("ⓘ", "How it works", checked=False, checkable=False)
        self.b_help.clicked.connect(self.help_clicked)
        lay.addWidget(self.b_help, 0, Qt.AlignHCenter)

    def _btn(self, glyph: str, tip: str, *, checked: bool, checkable: bool = True) -> QToolButton:
        b = QToolButton()
        b.setObjectName("rail")
        b.setText(glyph)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if checkable:
            b.setChecked(checked)
        elif checked:
            b.setProperty("active", True)
            b.setStyleSheet("QToolButton#rail { color: #52d8fa; background: #192a3d; }")
        return b


class HeaderBar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(69)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(24, 0, 24, 0)
        self.lay.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(logo_pixmap(56, tile=False))
        mark.setFixedSize(28, 28)
        mark.setScaledContents(True)
        mark.setStyleSheet("background: transparent;")
        word = QLabel('ANTHEM AUTO <span style="color:#39c6ec;">SYNCK</span> STUDIO')
        word.setStyleSheet("font-size: 17px; font-weight: 800; letter-spacing: 0px; background: transparent;")
        self.project = QLabel("●  Untitled Multicam Project")
        self.project.setStyleSheet("color:#8393a7; border-left:1px solid #263344; padding: 6px 14px; background: transparent;")
        self.lay.addWidget(mark)
        self.lay.addWidget(word)
        self.lay.addWidget(self.project)
        self.lay.addStretch(1)

    def add(self, w: QWidget) -> None:
        self.lay.addWidget(w)


class StatTile(QFrame):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.setObjectName("stat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 11, 15, 11)
        lay.setSpacing(2)
        self.name = QLabel(name)
        self.name.setStyleSheet("font-size: 11px; color: #8da0b7;")
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 20px; font-weight: 700;")
        lay.addWidget(self.name)
        lay.addWidget(self.value)

    def set_value(self, text: str, color: str = "#e8f0fa") -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")


class SummaryBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 12)
        lay.setSpacing(12)
        top = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(9)
        title = QLabel("Multicam Synchronization")
        title.setStyleSheet("font-size: 21px; font-weight: 700;")
        self.chip = QLabel("READY TO SYNC")
        self.chip.setObjectName("chip")
        row.addWidget(title)
        row.addWidget(self.chip)
        row.addStretch(1)
        sub = QLabel("Align multiple cameras and external audio using waveform analysis.")
        sub.setStyleSheet("color: #8393a7;")
        left.addLayout(row)
        left.addWidget(sub)
        self.formats = QLabel()
        self.formats.setTextFormat(Qt.RichText)
        self.formats.setStyleSheet("color: #8393a7;")
        top.addLayout(left, 1)
        top.addWidget(self.formats, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.addLayout(top)
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.t_tracks = StatTile("TOTAL TRACKS")
        self.t_clips = StatTile("MEDIA CLIPS")
        self.t_conf = StatTile("SYNC CONFIDENCE")
        self.t_dur = StatTile("PROJECT DURATION")
        for t in (self.t_tracks, self.t_clips, self.t_conf, self.t_dur):
            tiles.addWidget(t, 1)
        lay.addLayout(tiles)

    def set_formats(self, fps: str, rate: str) -> None:
        self.formats.setText(f'Frame rate <b style="color:#d8e4f0">{fps}</b> &nbsp;·&nbsp; Sample rate <b style="color:#d8e4f0">{rate}</b>')


STATE_COLORS = {"ready": "#79e3b5", "busy": "#ffca83", "done": "#79e3b5", "review": "#ffca83", "failed": "#f07478"}


class BottomBar(QFrame):
    prev_clicked = Signal()
    next_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("bottom")
        self.setMinimumHeight(123)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        tr = QWidget()
        tl = QVBoxLayout(tr)
        tl.setContentsMargins(22, 18, 22, 14)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.timecode = QLabel("00:00:00:00")
        self.timecode.setStyleSheet("font-size: 21px; font-weight: 700; letter-spacing: 1px;")
        self.b_prev = QPushButton("⏮"); self.b_prev.setObjectName("circle"); self.b_prev.setToolTip("Jump to previous clip start")
        self.b_play = QPushButton("▶"); self.b_play.setObjectName("circle")
        self.b_play.setEnabled(False)
        self.b_play.setToolTip("Synchronize first, then select a clip and play it with the reference")
        self.b_next = QPushButton("⏭"); self.b_next.setObjectName("circle"); self.b_next.setToolTip("Jump to next clip start")
        self.b_prev.clicked.connect(self.prev_clicked)
        self.b_next.clicked.connect(self.next_clicked)
        self.selection = QLabel("Select a clip to inspect it")
        self.selection.setStyleSheet("color: #8393a7; margin-left: 10px;")
        for w in (self.timecode, self.b_prev, self.b_play, self.b_next, self.selection):
            row.addWidget(w)
        row.addStretch(1)
        self.tagline = QLabel("Waveform-based synchronization • Multi-camera alignment")
        self.tagline.setStyleSheet("color: #8295a9; font-size: 11px;")
        tl.addLayout(row)
        tl.addWidget(self.tagline)
        tl.addStretch(1)
        lay.addWidget(tr, 1)

        sp = QFrame()
        sp.setObjectName("statuspanel")
        sp.setMinimumWidth(310)
        sl = QVBoxLayout(sp)
        sl.setContentsMargins(23, 16, 23, 14)
        line = QHBoxLayout()
        lbl = QLabel("Synchronization Status")
        lbl.setStyleSheet("font-weight: 700; background: transparent;")
        self.state = QLabel("● Ready")
        self.state.setStyleSheet("color: #79e3b5; font-weight: 700; background: transparent;")
        line.addWidget(lbl)
        line.addStretch(1)
        line.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        self.desc = QLabel("Import media and select Synchronize to align source clips.")
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #96a9b9; font-size: 11px; background: transparent;")
        sl.addLayout(line)
        sl.addWidget(self.progress)
        sl.addWidget(self.desc)
        sl.addStretch(1)
        lay.addWidget(sp)
        sp.setMaximumWidth(460)

    def set_state(self, kind: str, text: str) -> None:
        self.state.setText("● " + text)
        self.state.setStyleSheet(f"color: {STATE_COLORS.get(kind, '#79e3b5')}; font-weight: 700; background: transparent;")
