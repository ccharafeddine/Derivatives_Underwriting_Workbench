"""Application theming.

A professional dark-first theme (with a light alternative) applied app-wide via
a Qt style sheet. Charts render in their own web views and keep their light
plotly background, reading as cards against either theme.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

THEMES: tuple[str, ...] = ("dark", "light")

_DARK_QSS = """
QWidget { background-color: #1e222a; color: #e6e6e6;
          font-size: 13px; selection-background-color: #2f6fed; }
QMainWindow, QDialog { background-color: #1e222a; }
QTabWidget::pane { border: 1px solid #333a45; border-radius: 4px; }
QTabBar::tab { background: #262b34; color: #b8c0cc; padding: 7px 16px;
               border: 1px solid #333a45; border-bottom: none;
               border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #313845; color: #ffffff; }
QTabBar::tab:hover { background: #2c323d; }
QGroupBox { border: 1px solid #333a45; border-radius: 5px; margin-top: 10px;
            padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px;
                   color: #9aa4b2; }
QPushButton { background-color: #2f6fed; color: #ffffff; border: none;
              padding: 6px 14px; border-radius: 4px; }
QPushButton:hover { background-color: #3b7bf7; }
QPushButton:disabled { background-color: #3a414d; color: #7c8592; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background-color: #262b34; border: 1px solid #3a414d; border-radius: 4px;
    padding: 4px 6px; color: #e6e6e6; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2f6fed; }
QComboBox QAbstractItemView { background: #262b34;
    selection-background-color: #2f6fed; }
QTableWidget, QListWidget { background-color: #232830; border: 1px solid #333a45;
    gridline-color: #333a45; }
QHeaderView::section { background-color: #2a2f39; color: #9aa4b2;
    padding: 4px; border: none; border-right: 1px solid #333a45; }
QListWidget::item:selected, QTableWidget::item:selected {
    background: #2f6fed; color: #ffffff; }
QMenuBar { background-color: #191c23; }
QMenuBar::item:selected { background: #2f6fed; }
QMenu { background-color: #232830; border: 1px solid #333a45; }
QMenu::item:selected { background: #2f6fed; }
QProgressBar { border: 1px solid #333a45; border-radius: 4px; text-align: center;
    background: #262b34; }
QProgressBar::chunk { background-color: #2f6fed; border-radius: 3px; }
QStatusBar { background: #191c23; color: #9aa4b2; }
QSplitter::handle { background: #333a45; }
"""

_LIGHT_QSS = """
QWidget { color: #1a1a1a; font-size: 13px; selection-background-color: #2f6fed;
          selection-color: #ffffff; }
QTabWidget::pane { border: 1px solid #d5d9e0; border-radius: 4px; }
QTabBar::tab { background: #eef1f5; color: #444; padding: 7px 16px;
               border: 1px solid #d5d9e0; border-bottom: none;
               border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #ffffff; color: #111; }
QGroupBox { border: 1px solid #d5d9e0; border-radius: 5px; margin-top: 10px;
            padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px;
                   color: #666; }
QPushButton { background-color: #2f6fed; color: #ffffff; border: none;
              padding: 6px 14px; border-radius: 4px; }
QPushButton:hover { background-color: #3b7bf7; }
QPushButton:disabled { background-color: #c7ccd4; color: #8a909a; }
QProgressBar { border: 1px solid #d5d9e0; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background-color: #2f6fed; border-radius: 3px; }
"""


def stylesheet(theme: str) -> str:
    """Return the Qt style sheet for ``theme`` ("dark" or "light")."""
    return _LIGHT_QSS if theme == "light" else _DARK_QSS


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply ``theme`` to the whole application."""
    app.setStyleSheet(stylesheet(theme))
