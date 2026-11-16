"""Audio playback for sync review: plays the selected clip together with the reference at their timeline positions.

Playback uses the cached 16 kHz analysis audio, so it needs no extra decoding and cannot disturb the originals.
If two recordings are aligned correctly they sound like one voice; a misalignment is heard as an echo.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from app.paths import cache_dir
from core.media.extract import analysis_wav_path


class SyncPlayer(QObject):
    position_changed = Signal(float)   # timeline seconds
    stopped = Signal()
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._players: list[tuple[QMediaPlayer, QAudioOutput]] = []
        self._t0 = 0.0
        self._primary: QMediaPlayer | None = None
        self._primary_origin = 0.0     # timeline time of primary source position 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    @staticmethod
    def wav_for(media) -> Path | None:
        info = getattr(media, "info", None)
        if info is None or not info.audio:
            return None
        p = analysis_wav_path(media.path, info.audio[0].index, cache_dir() / "analysis")
        return p if p.is_file() else None

    def play(self, parts: list[tuple[Path, float, float]]) -> bool:
        """parts: (wav path, source position in seconds, timeline time of source position 0). First part drives the playhead."""
        self.stop()
        if not parts:
            return False
        for i, (wav, pos, origin) in enumerate(parts):
            out = QAudioOutput()
            out.setVolume(1.0)
            pl = QMediaPlayer()
            pl.setAudioOutput(out)
            pl.setSource(QUrl.fromLocalFile(str(wav)))
            pl.setPosition(int(max(0.0, pos) * 1000))
            pl.errorOccurred.connect(lambda _e, msg, self=self: self._on_error(msg))
            self._players.append((pl, out))
            if i == 0:
                self._primary, self._primary_origin = pl, origin
        for pl, _ in self._players:
            pl.play()
        self._timer.start()
        return True

    def _on_error(self, msg: str) -> None:
        self.stop()
        self.failed.emit(msg or "audio playback error")

    def stop(self) -> None:
        was = self._timer.isActive()
        self._timer.stop()
        for pl, out in self._players:
            pl.stop()
            pl.setSource(QUrl())
            pl.deleteLater()
            out.deleteLater()
        self._players, self._primary = [], None
        if was:
            self.stopped.emit()

    def _tick(self) -> None:
        pl = self._primary
        if pl is None:
            return
        if pl.playbackState() == QMediaPlayer.StoppedState and pl.position() > 0:
            self.stop()
            return
        self.position_changed.emit(self._primary_origin + pl.position() / 1000.0)
