import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AUTOSYNC_HEADLESS", "1")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    from ui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app
