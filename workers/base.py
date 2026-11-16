"""Cancellable background job with progress signals; keeps heavy work off the UI thread."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from app.errors import Cancelled

log = logging.getLogger(__name__)


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()


class Job(QObject):
    """Runs fn(progress, token) on a QThread. Emits finished(result) | failed(msg) | cancelled()."""
    progress = Signal(int, str)   # percent, message
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    done = Signal()               # always emitted last

    def __init__(self, fn: Callable[[Callable[[int, str], None], CancelToken], Any], name: str = "job") -> None:
        super().__init__()
        self.fn, self.name = fn, name
        self.token = CancelToken()
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.token.cancel()

    def wait(self, ms: int = 30000) -> bool:
        return self._thread.wait(ms)

    def _run(self) -> None:
        try:
            result = self.fn(lambda p, m="": self.progress.emit(int(p), m), self.token)
            if self.token.cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(result)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:  # reported, never swallowed
            log.exception("Job %s failed", self.name)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.done.emit()
            self._thread.quit()
