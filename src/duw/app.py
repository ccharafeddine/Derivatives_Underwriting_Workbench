"""Application entry point and main window wiring.

Builds the :class:`QApplication` and a traditional menu-bar
:class:`QMainWindow` hosting a :class:`QTabWidget` with the eight workflow tabs.
For now the tabs are empty placeholders; later sessions replace each with its
real widget. Run with ``python -m duw.app``.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from duw import __version__

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
    """Top-level window: menu bar plus the tabbed workflow."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Derivatives Underwriting Workbench")
        self.resize(1200, 800)

        self._build_menu_bar()
        self._build_tabs()

    def _build_menu_bar(self) -> None:
        """Create the traditional File / Edit / View / Settings menu bar."""
        menu_bar = self.menuBar()
        # Menus are created empty for now; actions are added in later sessions.
        menu_bar.addMenu("&File")
        menu_bar.addMenu("&Edit")
        menu_bar.addMenu("&View")
        menu_bar.addMenu("&Settings")

    def _build_tabs(self) -> None:
        """Create the central tab widget with the eight workflow tabs."""
        self.tabs = QTabWidget()
        for name in TAB_NAMES:
            self.tabs.addTab(_placeholder_tab(name), name)
        self.setCentralWidget(self.tabs)


def main(argv: list[str] | None = None) -> int:
    """Launch the application. Returns the Qt event-loop exit code."""
    args = argv if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName("Derivatives Underwriting Workbench")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
