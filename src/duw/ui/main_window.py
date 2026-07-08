"""Main window.

The composed :class:`QMainWindow`: a traditional File / Edit / View / Settings
menu bar, a :class:`QTabWidget` of the eight workflow tabs (Trade and
Counterparty are real input tabs; the rest are placeholders filled in later
sessions), a shared :class:`~duw.ui.app_state.AppState`, and a Run Analysis
action that enables once both inputs are valid. The Run action is not yet wired
to the pipeline — that happens in the analytics session. Qt lives here.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from duw.ui.app_state import AppState
from duw.ui.tabs.counterparty_tab import CounterpartyTab
from duw.ui.tabs.trade_tab import TradeTab

# The eight workflow tabs, in the order a run flows through them.
TAB_NAMES: tuple[str, ...] = (
    "Trade",
    "Counterparty",
    "Exposure",
    "Limits",
    "Collateral",
    "CVA",
    "Memo",
    "Pipeline",
)

# Tabs still awaiting their real widgets (filled in later sessions).
_PLACEHOLDER_TABS: tuple[str, ...] = (
    "Exposure",
    "Limits",
    "Collateral",
    "CVA",
    "Memo",
    "Pipeline",
)


def _placeholder_tab(name: str) -> QWidget:
    """Return an empty placeholder widget for a not-yet-built tab."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(f"{name} — coming soon")
    label.setObjectName(f"{name.lower()}_placeholder")
    layout.addWidget(label)
    layout.addStretch(1)
    return widget


class MainWindow(QMainWindow):
    """Top-level window: menu bar, tabbed workflow, and shared app state."""

    def __init__(self, app_state: AppState | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Derivatives Underwriting Workbench")
        self.resize(1200, 800)

        self.app_state = app_state or AppState()
        self.trade_tab = TradeTab(self.app_state)
        self.counterparty_tab = CounterpartyTab(self.app_state)

        self._build_tabs()
        self._build_menu_bar()
        self.statusBar().showMessage("Enter a trade and counterparty to run.")

        # Enable/disable the Run action as inputs become valid.
        self.app_state.tradeChanged.connect(self._update_run_enabled)
        self.app_state.counterpartyChanged.connect(self._update_run_enabled)
        self._update_run_enabled()

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self.trade_tab, "Trade")
        self.tabs.addTab(self.counterparty_tab, "Counterparty")
        for name in _PLACEHOLDER_TABS:
            self.tabs.addTab(_placeholder_tab(name), name)
        self.setCentralWidget(self.tabs)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        self.run_action = QAction("&Run Analysis", self)
        self.run_action.setShortcut("Ctrl+R")
        self.run_action.triggered.connect(self._on_run)
        file_menu.addAction(self.run_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        menu_bar.addMenu("&Edit")
        menu_bar.addMenu("&View")
        menu_bar.addMenu("&Settings")

    def _update_run_enabled(self, *_args: object) -> None:
        ready = self.app_state.is_ready()
        self.run_action.setEnabled(ready)
        if ready:
            self.statusBar().showMessage("Ready to run.")
        else:
            self.statusBar().showMessage("Enter a valid trade and counterparty to run.")

    def _on_run(self) -> None:
        # Not yet wired to the pipeline worker (analytics session). For now just
        # confirm the inputs are captured.
        if not self.app_state.is_ready():
            return
        counterparty, _existing, trade = self.app_state.run_inputs()
        self.statusBar().showMessage(
            f"Run requested: {trade.product} vs {counterparty.name} "
            "(pipeline wiring pending)."
        )
