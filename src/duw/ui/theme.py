"""Application theming.

Three app-wide Qt style sheets:

- **graphite** (default): the Graphite design system shared with Portfolio
  Analyzer. Neutral graphite surfaces separated by 1px hairlines, one blue
  accent for selection and primary actions, green/red kept for gains, losses
  and breaches, and Inter with tabular numerals. Tokens live in
  :data:`GRAPHITE`; widgets that paint their own colours read them through
  :func:`tokens`.
- **dark**: the original Bloomberg-terminal look (amber on near-black,
  monospaced grids), kept selectable as "Terminal (amber)".
- **light**: the original warm beige "paper" theme.

Charts follow the active theme through
:func:`duw.ui.widgets.charts.apply_chart_theme`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

THEMES: tuple[str, ...] = ("graphite", "dark", "light")
DEFAULT_THEME = "graphite"
THEME_LABELS: dict[str, str] = {
    "graphite": "Graphite",
    "dark": "Terminal (amber)",
    "light": "Paper (light)",
}

# Graphite design tokens (identical values to Portfolio Analyzer's GRAPHITE).
GRAPHITE: dict[str, str] = {
    "bg": "#0E1114",
    "panel": "#12161A",
    "card": "#12161A",
    "card_alt": "#151A1F",
    "raised": "#1B2128",
    "border": "#22272E",
    "border_light": "#2D333B",
    "accent": "#2F6FEB",
    "accent_hover": "#255FD0",
    "accent_soft": "#4C8DFF",
    "text": "#E6EDF3",
    "text_slate": "#ADBAC7",
    "text_muted": "#768390",
    "text_faint": "#636E7B",
    "green": "#3FB950",
    "red": "#F47067",
    "amber": "#D4A72C",
}

# Approximate tokens for the legacy themes, for self-painted widgets.
_LEGACY_TOKENS: dict[str, dict[str, str]] = {
    "dark": GRAPHITE
    | {
        "bg": "#0b0c0e",
        "panel": "#0e0f12",
        "card": "#141619",
        "raised": "#1c1f25",
        "border": "#24272e",
        "border_light": "#2f333b",
        "accent": "#f2a007",
        "accent_soft": "#ffab33",
        "text": "#d2cbb9",
        "text_slate": "#cbc4b2",
        "text_muted": "#8f8a7c",
        "text_faint": "#6b6656",
        "green": "#2ca02c",
        "red": "#d62728",
        "amber": "#ffab33",
    },
    "light": GRAPHITE
    | {
        "bg": "#e7e0cf",
        "panel": "#efe8d8",
        "card": "#f5efe2",
        "raised": "#ded5c1",
        "border": "#c4b89e",
        "border_light": "#d5cbb4",
        "accent": "#2b62d9",
        "accent_soft": "#2b62d9",
        "text": "#2a2419",
        "text_slate": "#5c5240",
        "text_muted": "#6b5f49",
        "text_faint": "#837a67",
        "green": "#2e7d32",
        "red": "#c62828",
        "amber": "#b26a00",
    },
}


def tokens(theme: str | None = None) -> dict[str, str]:
    """Colour tokens for ``theme`` (default: the active theme)."""
    key = theme or _current
    return GRAPHITE if key == "graphite" else _LEGACY_TOKENS.get(key, GRAPHITE)


def _graphite_qss() -> str:
    t = GRAPHITE
    return f"""
QWidget {{ background-color: {t["bg"]}; color: {t["text"]};
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px; selection-background-color: {t["accent"]};
    selection-color: #FFFFFF; }}
QMainWindow, QDialog {{ background-color: {t["bg"]}; }}
QDialog {{ background-color: {t["panel"]}; }}
QToolTip {{ background-color: {t["panel"]}; color: {t["text"]};
    border: 1px solid {t["border_light"]}; padding: 6px 8px; }}
QMenuBar {{ background-color: {t["panel"]}; color: {t["text_slate"]};
    border-bottom: 1px solid {t["border"]}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {t["raised"]}; color: {t["text"]}; }}
QMenu {{ background-color: {t["panel"]}; border: 1px solid {t["border_light"]};
    color: {t["text"]}; }}
QMenu::item {{ padding: 5px 22px; }}
QMenu::item:selected {{ background: {t["accent"]}; color: #FFFFFF; }}
QMenu::separator {{ height: 1px; background: {t["border"]}; margin: 4px 0; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {t["border"]}; }}
QTabWidget#pageStack::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t["text_muted"]}; padding: 5px 12px;
    border: none; margin-right: 2px; }}
QTabBar::tab:selected {{ color: {t["text"]}; border-bottom: 2px solid {t["accent"]}; }}
QTabBar::tab:hover {{ color: {t["text_slate"]}; }}

QGroupBox {{ background-color: {t["panel"]}; border: 1px solid {t["border"]};
    border-radius: 0px; margin-top: 22px; padding: 10px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
    left: 0px; top: 4px; padding: 0 2px; color: {t["text_slate"]};
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; }}

QPushButton {{ background-color: {t["raised"]}; color: {t["text"]};
    border: 1px solid {t["border_light"]}; border-radius: 3px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {t["accent"]}; }}
QPushButton:pressed {{ background-color: {t["border"]}; }}
QPushButton:disabled {{ color: {t["text_faint"]}; border-color: {t["border"]};
    background-color: {t["panel"]}; }}
QPushButton#primary, QDialogButtonBox QPushButton:default {{
    background-color: {t["accent"]}; border-color: {t["accent"]}; color: #FFFFFF;
    font-weight: 600; }}
QPushButton#primary:hover {{ background-color: {t["accent_hover"]}; }}
QPushButton#primary:disabled {{ background-color: {t["border_light"]};
    border-color: {t["border_light"]}; color: {t["text_muted"]}; }}
QPushButton#ghost {{ background: transparent; }}
QToolButton {{ background: transparent; color: {t["text"]};
    border: 1px solid {t["border_light"]}; border-radius: 3px; padding: 4px 10px; }}
QToolButton:hover {{ border-color: {t["accent"]}; }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}

QCheckBox, QRadioButton {{ color: {t["text_slate"]}; spacing: 7px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 2px;
    border: 1px solid {t["border_light"]}; background-color: {t["card"]}; }}
QCheckBox::indicator:checked {{ background-color: {t["accent"]};
    border-color: {t["accent"]}; }}
QCheckBox::indicator:hover {{ border-color: {t["accent"]}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background-color: {t["card_alt"]}; border: 1px solid {t["border_light"]};
    border-radius: 3px; padding: 3px 6px; color: {t["text"]}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus {{ border-color: {t["accent"]}; }}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{
    color: {t["text_faint"]}; border-color: {t["border"]}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{ background: {t["panel"]}; color: {t["text"]};
    border: 1px solid {t["border_light"]}; selection-background-color: {t["accent"]}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {{ width: 0px; border: none; }}

QTableWidget, QTableView, QListWidget, QTreeWidget {{
    background-color: {t["panel"]}; alternate-background-color: {t["card_alt"]};
    border: 1px solid {t["border"]}; gridline-color: {t["border"]};
    color: {t["text"]}; outline: 0; }}
QTableWidget::item, QTableView::item {{ padding: 2px 6px; border: none;
    border-bottom: 1px solid {t["border"]}; }}
QTableWidget::item:selected, QListWidget::item:selected {{
    background: {t["raised"]}; color: {t["text"]}; }}
QHeaderView::section {{ background-color: {t["panel"]}; color: {t["text_muted"]};
    padding: 4px 6px; border: none; border-bottom: 1px solid {t["border"]};
    font-size: 10px; font-weight: 600; text-transform: uppercase; }}
QTableCornerButton::section {{ background: {t["panel"]}; border: none; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle {{ background: {t["border_light"]}; border-radius: 4px;
    min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {t["text_faint"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {t["bg"]}; }}
QSplitter::handle:horizontal {{ width: 12px; }}
QSplitter::handle:vertical {{ height: 12px; }}
QProgressBar {{ background: {t["card"]}; border: none; height: 6px;
    color: transparent; }}
QProgressBar::chunk {{ background-color: {t["accent"]}; }}
QStatusBar {{ background: {t["panel"]}; color: {t["text_muted"]};
    border-top: 1px solid {t["border"]}; font-size: 11px; }}
QStatusBar::item {{ border: none; }}
QToolBar {{ background: {t["panel"]}; border: none; }}

QLabel {{ background: transparent; color: {t["text"]}; }}
QLabel#helpBadge {{ color: {t["text_muted"]}; background: transparent;
    border: 1px solid {t["border_light"]}; border-radius: 7px; font-size: 9px;
    font-weight: 600; }}
QLabel#helpBadge:hover {{ color: {t["text"]}; border-color: {t["accent"]}; }}
QLabel#muted, QLabel#commentary {{ color: {t["text_muted"]}; }}
QLabel#sectionLabel {{ color: {t["text_slate"]}; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em; }}

/* -- App shell ---------------------------------------------------------- */
QFrame#topBar {{ background-color: {t["panel"]};
    border-bottom: 1px solid {t["border"]}; }}
QLabel#brand {{ color: {t["text"]}; font-weight: 600; letter-spacing: 0.04em; }}
QLabel#ctxLabel {{ color: {t["text_muted"]}; }}
QToolButton#ctxChip {{ color: {t["text"]}; border: 1px solid {t["border_light"]};
    border-radius: 3px; padding: 3px 10px; }}
QToolButton#ctxChip:hover {{ border-color: {t["accent"]}; }}
QLabel#exampleTag {{ color: {t["amber"]}; border: 1px solid #5A4A1A;
    border-radius: 2px; padding: 1px 6px; font-size: 10px; font-weight: 600;
    letter-spacing: 0.06em; }}
QFrame#navPanel {{ background-color: #101418; border-right: 1px solid {t["border"]}; }}
QListWidget#navList {{ background: transparent; border: none; outline: 0; }}
QListWidget#navList::item {{ color: {t["text_slate"]}; padding: 5px 14px;
    border: none; border-left: 2px solid transparent; }}
QListWidget#navList::item:selected {{ color: {t["text"]}; background: {t["raised"]};
    border-left: 2px solid {t["accent"]}; }}
QListWidget#navList::item:hover:!selected {{ color: {t["text"]}; }}
QFrame#pageHeader {{ background: transparent; }}
QLabel#pageTitle {{ color: {t["text"]}; font-size: 18px; font-weight: 600; }}
QLabel#pageSub {{ color: {t["text_muted"]}; }}
QFrame#kpiStrip {{ background-color: {t["panel"]}; border: 1px solid {t["border"]}; }}
QFrame#kpiCell {{ border: none; border-right: 1px solid {t["border"]};
    background: transparent; }}
QLabel#kpiLabel {{ color: {t["text_muted"]}; font-size: 10px; font-weight: 600;
    letter-spacing: 0.06em; }}
QLabel#kpiValue {{ color: {t["text"]}; font-size: 17px; font-weight: 500; }}
QLabel#kpiSub {{ color: {t["text_muted"]}; font-size: 11px; }}
QFrame#panel {{ background-color: {t["panel"]}; border: 1px solid {t["border"]}; }}
QLabel#panelTitle {{ color: {t["text_slate"]}; font-size: 11px; font-weight: 600;
    letter-spacing: 0.06em; padding: 7px 12px;
    border-bottom: 1px solid {t["border"]}; }}
QLabel#panelNote {{ color: {t["text_muted"]}; padding: 8px 12px;
    border-top: 1px solid {t["border"]}; }}
QLabel#chipOk {{ color: {t["green"]}; border: 1px solid #1F4D2A; padding: 1px 7px;
    font-size: 10px; }}
QLabel#chipWarn {{ color: {t["amber"]}; border: 1px solid #5A4A1A; padding: 1px 7px;
    font-size: 10px; }}
QLabel#chipBad {{ color: {t["red"]}; border: 1px solid #5C2B28; padding: 1px 7px;
    font-size: 10px; }}
QLabel#statusLabel {{ color: {t["text_muted"]}; padding: 0 6px; }}
"""

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


_current = DEFAULT_THEME


def current_theme() -> str:
    """Return the theme last applied via :func:`apply_theme` (default Graphite).

    Lets widgets built after startup (e.g. chart views) pick up the active theme
    without threading it through every constructor.
    """
    return _current


def normalize_theme(theme: str | None) -> str:
    """A known theme key (unknown or empty values fall back to Graphite)."""
    return theme if theme in THEMES else DEFAULT_THEME


def stylesheet(theme: str) -> str:
    """Return the Qt style sheet for ``theme``."""
    key = normalize_theme(theme)
    if key == "light":
        return _LIGHT_QSS
    if key == "dark":
        return _DARK_QSS
    return _graphite_qss()


def apply_tabular_font(app: QApplication) -> None:
    """Inter with tabular (fixed-width) numerals app-wide, so figures line up."""
    from PySide6.QtGui import QFont

    font = QFont(app.font())
    font.setFamilies(["Inter", "Segoe UI", "Helvetica Neue", "Arial"])
    if hasattr(font, "setFeature"):
        try:
            font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
    app.setFont(font)


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply ``theme`` to the whole application."""
    global _current
    _current = normalize_theme(theme)
    apply_tabular_font(app)
    app.setStyleSheet(stylesheet(_current))
