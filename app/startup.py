"""Application bootstrap: logging, config, dependency check, Qt event loop."""
from __future__ import annotations

import logging
import os
import sys

from app import APP_NAME, __version__
from app.config import Config
from app.dependencies import check_dependencies
from app.logging_setup import install_exception_hooks, setup_logging


def run(argv: list[str]) -> int:
    log = setup_logging()
    log.info("%s %s starting (python %s, %s)", APP_NAME, __version__, sys.version.split()[0], sys.platform)

    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AutoSyncStudio")
    from ui.chrome import app_icon
    app.setWindowIcon(app_icon())

    def show_error(kind: str, message: str) -> None:
        if QApplication.instance() is not None and not os.environ.get("AUTOSYNC_HEADLESS"):
            QMessageBox.critical(None, APP_NAME, f"Unexpected error ({kind}):\n\n{message}\n\nDetails were written to the log file.")

    install_exception_hooks(show_error)

    config = Config.load()
    deps = check_dependencies(config.ffmpeg_path, config.ffprobe_path)

    from ui.main_window import MainWindow
    from ui.theme import apply_theme

    apply_theme(app)
    window = MainWindow(config, deps)
    window.show()

    if not deps.ok:
        log.warning("Dependency problems: %s", deps.problems())
        if not os.environ.get("AUTOSYNC_HEADLESS"):
            QMessageBox.warning(window, APP_NAME, "Some dependencies are missing:\n\n" + "\n".join(deps.problems()))

    if not os.environ.get("AUTOSYNC_HEADLESS") and not os.environ.get("AUTOSYNC_SMOKE"):
        window.start_update_check()

    if os.environ.get("AUTOSYNC_SMOKE"):  # launch-and-exit mode for automated verification
        from PySide6.QtCore import QTimer
        QTimer.singleShot(int(os.environ.get("AUTOSYNC_SMOKE_MS", "800")), app.quit)

    code = app.exec()
    config.save()
    log.info("Exiting with code %s", code)
    return code
