"""Dark charcoal theme: teal primary accent, subtle orange highlights."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#1b1d20"
PANEL = "#23262a"
PANEL_ALT = "#2a2e33"
BORDER = "#3a3f45"
TEXT = "#d8dce0"
TEXT_DIM = "#8b929a"
TEAL = "#1fb5a8"
TEAL_DARK = "#168a80"
ORANGE = "#e8913a"
RED = "#d9534f"
GREEN = "#3fb37f"

QSS = f"""
* {{ font-size: 12px; }}
QMainWindow, QDialog, QWidget {{ background: {BG}; color: {TEXT}; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px; spacing: 4px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 5px 7px; color: {TEXT}; }}
QToolButton:hover {{ background: {PANEL_ALT}; border-color: {BORDER}; }}
QToolButton:pressed {{ background: {BORDER}; }}
QToolButton:disabled {{ color: #5b6168; }}
QToolButton#primary {{ background: {TEAL_DARK}; color: white; border-color: {TEAL}; font-weight: 600; }}
QToolButton#primary:hover {{ background: {TEAL}; }}
QToolButton#primary:disabled {{ background: {PANEL_ALT}; color: #5b6168; border-color: {BORDER}; }}
QToolButton#danger:enabled {{ color: {ORANGE}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QSplitter::handle:hover {{ background: {TEAL}; }}
QTreeWidget, QTableWidget, QListWidget, QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 3px; selection-background-color: {TEAL_DARK}; selection-color: white;
    alternate-background-color: {PANEL_ALT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {TEAL}; }}
QHeaderView::section {{ background: {PANEL_ALT}; color: {TEXT_DIM}; border: none; border-right: 1px solid {BORDER}; padding: 4px 6px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {PANEL}; padding: 6px 14px; border: 1px solid {BORDER}; border-bottom: none; color: {TEXT_DIM}; }}
QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; border-top: 2px solid {TEAL}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {TEXT_DIM}; padding: 0 4px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QProgressBar {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 3px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {TEAL}; border-radius: 2px; }}
QPushButton {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {TEAL}; }}
QPushButton:default {{ background: {TEAL_DARK}; border-color: {TEAL}; color: white; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; }} QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; }} QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }} QMenu::item:selected {{ background: {TEAL_DARK}; }}
QToolTip {{ background: {PANEL_ALT}; color: {TEXT}; border: 1px solid {TEAL}; }}
QLabel#heading {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL_ALT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL_ALT))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(TEAL_DARK))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_DIM))
    app.setPalette(pal)
    font = QFont("Segoe UI" if app.platformName() == "windows" else "Helvetica Neue", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(QSS)
