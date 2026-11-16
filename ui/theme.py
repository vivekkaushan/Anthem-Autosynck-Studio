"""Dark charcoal theme: teal primary accent, subtle orange highlights."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0b1019"
PANEL = "#111824"
PANEL_ALT = "#17212e"
RAIL = "#0c131e"
BORDER = "#263344"
TEXT = "#e8f0fa"
TEXT_DIM = "#8393a7"
TEAL = "#39c6ec"          # primary accent (cyan)
TEAL_DARK = "#137baf"
ORANGE = "#ffb45c"
RED = "#f07478"
GREEN = "#69d5a5"

QSS = f"""
* {{ font-size: 12px; }}
QMainWindow, QDialog, QWidget {{ background: {BG}; color: {TEXT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {TEAL}; }}
QTreeWidget, QTableWidget, QListWidget, QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; selection-background-color: #1d4f6b; selection-color: white;
    alternate-background-color: {PANEL_ALT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {TEAL}; }}
QHeaderView::section {{ background: {PANEL_ALT}; color: {TEXT_DIM}; border: none; border-right: 1px solid {BORDER}; padding: 5px 7px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; }}
QTabBar::tab {{ background: {PANEL}; padding: 7px 14px; border: 1px solid {BORDER}; border-bottom: none; color: {TEXT_DIM};
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {PANEL_ALT}; color: {TEXT}; border-top: 2px solid {TEAL}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 6px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {TEXT_DIM}; padding: 0 4px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QProgressBar {{ background: #2b3a48; border: none; border-radius: 4px; text-align: center; height: 7px; max-height: 7px; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1da9d4, stop:1 #62e6be); border-radius: 4px; }}
QPushButton {{ background: #203044; border: 1px solid #33465b; border-radius: 8px; padding: 9px 15px; font-weight: 600; color: #e5edf6; }}
QPushButton:hover {{ background: #28405a; }}
QPushButton:disabled {{ background: #131d2a; color: #4f6074; border-color: #223044; }}
QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #20add1, stop:1 #137baf); border-color: #32bbdf; color: white; }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2bc0e6, stop:1 #1a8fc9); }}
QPushButton#primary:disabled {{ background: #131d2a; color: #4f6074; border-color: #223044; }}
QPushButton#ghost {{ background: #131d2a; }}
QPushButton#ghost:hover {{ background: #1a2738; }}
QPushButton#update {{ background: #163d34; border: 1px solid #327a66; color: #91f3cf; }}
QPushButton#update:hover {{ background: #1c4d41; }}
QPushButton#danger {{ background: #3a1f26; border-color: #8a3f4a; color: #ffb0b6; }}
QPushButton#tool {{ background: #1b2837; border: 1px solid #2b3c50; border-radius: 7px; color: #a8bdcf; padding: 5px 10px; font-weight: 500; }}
QPushButton#tool:hover {{ background: #223347; }}
QPushButton#circle {{ background: #1e2c3e; border: 1px solid #36475c; border-radius: 16px; padding: 0; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; color: #d5e8f7; font-size: 13px; }}
QPushButton#circle:hover {{ background: #28405a; }}
QPushButton#circle:disabled {{ color: #4f6074; background: #131d2a; border-color: #223044; }}
QToolButton#rail {{ background: transparent; border: none; border-radius: 10px; color: #8da0b6; font-size: 20px; min-width: 43px; max-width: 43px; min-height: 43px; max-height: 43px; }}
QToolButton#rail:hover {{ color: #52d8fa; background: #192a3d; }}
QToolButton#rail:checked {{ color: #52d8fa; background: #192a3d; }}
QToolButton#menu {{ background: #203044; border: 1px solid #33465b; border-radius: 8px; padding: 9px 15px; font-weight: 600; color: #e5edf6; }}
QToolButton#menu:hover {{ background: #28405a; }}
QToolButton#menu::menu-indicator {{ image: none; width: 0; }}
QFrame#stat {{ background: #141e2b; border: 1px solid {BORDER}; border-radius: 11px; }}
QFrame#stat QLabel {{ background: transparent; }}
QFrame#topbar {{ background: #111927; border-bottom: 1px solid {BORDER}; }}
QFrame#rail {{ background: {RAIL}; border-right: 1px solid {BORDER}; }}
QFrame#bottom {{ background: #121c29; border-top: 1px solid {BORDER}; }}
QFrame#statuspanel {{ background: #121c29; border-left: 1px solid {BORDER}; }}
QFrame#timelinebar {{ background: #151e2b; border-top: 1px solid {BORDER}; border-bottom: 1px solid {BORDER}; }}
QLabel#chip {{ background: #193044; border: 1px solid #25506b; border-radius: 6px; padding: 4px 9px; color: #81def8; font-size: 11px; }}
QLabel#count {{ background: #273748; border-radius: 5px; padding: 3px 8px; color: #b6cad9; font-size: 11px; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; }} QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; }} QScrollBar::handle:horizontal {{ background: #34455a; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QMenu {{ background: #162131; border: 1px solid #33465b; padding: 4px; }} QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: #1d4f6b; }} QMenu::item:disabled {{ color: #4f6074; }}
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
    pal.setColor(QPalette.Highlight, QColor("#1d4f6b"))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_DIM))
    app.setPalette(pal)
    font = QFont("Segoe UI" if app.platformName() == "windows" else "Helvetica Neue", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(QSS)
