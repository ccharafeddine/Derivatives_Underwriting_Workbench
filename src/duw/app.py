"""Application entry point and main window wiring.

Builds the :class:`QApplication` and shows the :class:`MainWindow` (defined in
:mod:`duw.ui.main_window`). Run with ``python -m duw.app``.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from duw import __version__
from duw.config import KEY_THEME, AppSettings
from duw.ui.main_window import TAB_NAMES, MainWindow
from duw.ui.theme import apply_theme

__all__ = ["MainWindow", "TAB_NAMES", "main"]


def main(argv: list[str] | None = None) -> int:
    """Launch the application. Returns the Qt event-loop exit code."""
    args = argv if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName("Derivatives Underwriting Workbench")
    app.setApplicationVersion(__version__)

    apply_theme(app, AppSettings().get_str(KEY_THEME))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
