"""Application theming.

Two app-wide Qt style sheets:

- **dark** — a Bloomberg-terminal aesthetic: near-black panels, amber accents, and
  monospaced data grids, for the trading-desk feel.
- **light** — a warm beige "paper" theme (not stark white) with dark, high-contrast
  text, easier on the eyes than a bright white UI.

Charts render in their own web views with a light plotly background, reading as
cards against either theme.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

THEMES: tuple[str, ...] = ("dark", "light")

# ---------------------------------------------------------------------------
# Dark — Bloomberg-terminal style: near-black ground, amber accents, mono grids.
# ---------------------------------------------------------------------------
_DARK_QSS = """
QWidget { background-color: #0b0c0e; color: #d2cbb9;
          font-size: 13px; selection-background-color: #b56b00;
          selection-color: #0a0a0a; }
QMainWindow, QDialog { background-color: #0b0c0e; }
QToolTip { background-color: #15171b; color: #ffb733; border: 1px solid #3a2f14; }
QTabWidget::pane { border: 1px solid #24272e; border-radius: 3px; }
QTabBar::tab { background: #141519; color: #8f8a7c; padding: 7px 16px;
               border: 1px solid #24272e; border-bottom: none;
               border-top-left-radius: 3px; border-top-right-radius: 3px; }
QTabBar::tab:selected { background: #1c1f25; color: #ffab33;
               border-bottom: 2px solid #f2a007; }
QTabBar::tab:hover { background: #191b20; color: #cbc4b2; }
QGroupBox { border: 1px solid #24272e; border-radius: 4px; margin-top: 10px;
            padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px;
                   color: #ffab33; text-transform: uppercase;
                   letter-spacing: 1px; }
QPushButton { background-color: #f2a007; color: #0a0a0a; border: none;
              font-weight: 600; padding: 6px 14px; border-radius: 3px; }
QPushButton:hover { background-color: #ffb733; }
QPushButton:pressed { background-color: #d98e00; }
QPushButton:disabled { background-color: #2a2c33; color: #6b6656; }
QCheckBox { color: #d2cbb9; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background-color: #141619; border: 1px solid #2a2d34; border-radius: 3px;
    padding: 4px 6px; color: #ffce7a;
    font-family: "Consolas", "DejaVu Sans Mono", monospace; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #f2a007; }
QComboBox QAbstractItemView { background: #141619; color: #d2cbb9;
    selection-background-color: #b56b00; selection-color: #0a0a0a; }
QTableWidget, QListWidget { background-color: #0e0f12; border: 1px solid #24272e;
    gridline-color: #23262c; color: #d8d1bf;
    font-family: "Consolas", "DejaVu Sans Mono", monospace; }
QHeaderView::section { background-color: #141519; color: #ffab33;
    padding: 4px; border: none; border-right: 1px solid #23262c;
    text-transform: uppercase; letter-spacing: 1px; }
QListWidget::item:selected, QTableWidget::item:selected {
    background: #b56b00; color: #0a0a0a; }
QToolBar { background: #0e0f12; border: none; border-bottom: 1px solid #24272e;
    spacing: 6px; padding: 4px 6px; }
QToolButton { background: #f2a007; color: #0a0a0a; font-weight: 600;
    padding: 5px 14px; border-radius: 3px; }
QToolButton:hover { background: #ffb733; }
QToolButton:disabled { background: #2a2c33; color: #6b6656; }
QMenuBar { background-color: #060708; color: #cbc4b2; }
QMenuBar::item:selected { background: #f2a007; color: #0a0a0a; }
QMenu { background-color: #101216; border: 1px solid #24272e; color: #d2cbb9; }
QMenu::item:selected { background: #b56b00; color: #0a0a0a; }
QProgressBar { border: 1px solid #24272e; border-radius: 3px; text-align: center;
    background: #141619; color: #d2cbb9; }
QProgressBar::chunk { background-color: #f2a007; border-radius: 2px; }
QStatusBar { background: #060708; color: #ffab33; }
QSplitter::handle { background: #24272e; }
QLabel#helpBadge { color: #ffab33; background: #141519; border: 1px solid #3a2f14;
    border-radius: 8px; font-weight: bold; font-family: sans-serif; }
QLabel#helpBadge:hover { background: #241d0c; }
QScrollBar:vertical, QScrollBar:horizontal { background: #0e0f12; border: none; }
QScrollBar::handle { background: #2f333b; border-radius: 3px; }
QScrollBar::handle:hover { background: #45403a; }
"""

# ---------------------------------------------------------------------------
# Light — warm beige "paper", not stark white, with dark high-contrast text.
# ---------------------------------------------------------------------------
_LIGHT_QSS = """
QWidget { background-color: #e7e0cf; color: #2a2419;
          font-size: 13px; selection-background-color: #2b62d9;
          selection-color: #ffffff; }
QMainWindow, QDialog { background-color: #e7e0cf; }
QToolTip { background-color: #f2ecdd; color: #2a2419; border: 1px solid #c4b89e; }
QTabWidget::pane { border: 1px solid #c4b89e; border-radius: 4px;
                   background: #efe8d8; }
QTabBar::tab { background: #dcd4c0; color: #5c5240; padding: 7px 16px;
               border: 1px solid #c4b89e; border-bottom: none;
               border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #f5efe2; color: #1c1710;
               border-bottom: 2px solid #2b62d9; }
QTabBar::tab:hover { background: #e4ddca; }
QGroupBox { border: 1px solid #c4b89e; border-radius: 5px; margin-top: 10px;
            padding-top: 8px; font-weight: 600; background: #efe8d8; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px;
                   color: #6b5f49; }
QPushButton { background-color: #2b62d9; color: #ffffff; border: none;
              padding: 6px 14px; border-radius: 4px; }
QPushButton:hover { background-color: #3a72ef; }
QPushButton:pressed { background-color: #2455c0; }
QPushButton:disabled { background-color: #c8beaa; color: #837a67; }
QCheckBox { color: #2a2419; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background-color: #f5efe2; border: 1px solid #c4b89e; border-radius: 4px;
    padding: 4px 6px; color: #2a2419; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2b62d9; }
QComboBox QAbstractItemView { background: #f5efe2; color: #2a2419;
    selection-background-color: #2b62d9; selection-color: #ffffff; }
QTableWidget, QListWidget { background-color: #f3ecdd; border: 1px solid #c4b89e;
    gridline-color: #d5cbb4; color: #2a2419; }
QHeaderView::section { background-color: #ded5c1; color: #5c5240;
    padding: 4px; border: none; border-right: 1px solid #c4b89e; }
QListWidget::item:selected, QTableWidget::item:selected {
    background: #2b62d9; color: #ffffff; }
QToolBar { background: #ded5c1; border: none; border-bottom: 1px solid #c4b89e;
    spacing: 6px; padding: 4px 6px; }
QToolButton { background: #2b62d9; color: #ffffff; font-weight: 600;
    padding: 5px 14px; border-radius: 4px; }
QToolButton:hover { background: #3a72ef; }
QToolButton:disabled { background: #c8beaa; color: #837a67; }
QMenuBar { background-color: #ded5c1; color: #2a2419; }
QMenuBar::item:selected { background: #2b62d9; color: #ffffff; }
QMenu { background-color: #f2ecdd; border: 1px solid #c4b89e; color: #2a2419; }
QMenu::item:selected { background: #2b62d9; color: #ffffff; }
QProgressBar { border: 1px solid #c4b89e; border-radius: 4px; text-align: center;
    background: #f5efe2; color: #2a2419; }
QProgressBar::chunk { background-color: #2b62d9; border-radius: 3px; }
QStatusBar { background: #ded5c1; color: #6b5f49; }
QSplitter::handle { background: #c4b89e; }
QLabel#helpBadge { color: #2b62d9; background: #f5efe2; border: 1px solid #c4b89e;
    border-radius: 8px; font-weight: bold; font-family: sans-serif; }
QLabel#helpBadge:hover { background: #e7ecfb; }
"""


_current = "dark"


def current_theme() -> str:
    """Return the theme last applied via :func:`apply_theme` (default "dark").

    Lets widgets built after startup (e.g. chart views) pick up the active theme
    without threading it through every constructor.
    """
    return _current


def stylesheet(theme: str) -> str:
    """Return the Qt style sheet for ``theme`` ("dark" or "light")."""
    return _LIGHT_QSS if theme == "light" else _DARK_QSS


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply ``theme`` to the whole application."""
    global _current
    _current = "light" if theme == "light" else "dark"
    app.setStyleSheet(stylesheet(theme))
