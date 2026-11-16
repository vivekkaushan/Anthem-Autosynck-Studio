"""Rotating file + console logging and a global exception hook."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from typing import Callable

from app.paths import log_dir

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(h, "_autosync", False) for h in root.handlers):
        fh = RotatingFileHandler(log_dir() / "autosync.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        sh = logging.StreamHandler(sys.stderr)
        for h in (fh, sh):
            h.setFormatter(logging.Formatter(_FMT))
            h._autosync = True  # type: ignore[attr-defined]
            root.addHandler(h)
    return logging.getLogger("autosync")


def install_exception_hooks(on_error: Callable[[str, str], None] | None = None) -> None:
    """Log every uncaught exception (main + threads) and optionally notify the UI."""
    log = logging.getLogger("autosync.uncaught")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        if on_error:
            on_error(exc_type.__name__, str(exc))

    def thread_hook(args: threading.ExceptHookArgs):
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
