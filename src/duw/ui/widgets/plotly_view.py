"""A Qt view that renders a plotly figure.

Wraps a :class:`QWebEngineView` and displays a plotly figure by rendering it to
self-contained HTML with plotly.js inlined, so charts work fully offline (no CDN
fetch). The rendered figure and HTML are kept as attributes so headless tests
can assert a figure was produced without inspecting pixels. If the web engine is
unavailable for any reason, the widget degrades to a text placeholder.

The HTML is loaded from a temporary file rather than via ``setHtml``:
``QWebEngineView.setHtml`` encodes the content into a ``data:`` URL and silently
fails above roughly 2 MB (a Chromium limit), and a plotly document with inlined
plotly.js is several megabytes. Loading a local file has no such limit.
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from PySide6.QtCore import QTemporaryDir, QUrl
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlotlyView(QWidget):
    """Displays a plotly :class:`~plotly.graph_objects.Figure`."""

    def __init__(self) -> None:
        super().__init__()
        self.figure: go.Figure | None = None
        self.html: str = ""
        self._tmpdir = QTemporaryDir()
        self._counter = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view: QWidget
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView

            self._view = QWebEngineView()
            self._web = True
        except Exception:
            self._view = QLabel("Charts require QtWebEngine.")
            self._view.setWordWrap(True)
            self._web = False
        layout.addWidget(self._view)

    def set_figure(self, figure: go.Figure) -> None:
        """Render ``figure`` into the view."""
        self.figure = figure
        self.html = figure.to_html(include_plotlyjs="inline", full_html=True)
        self._load_html(self.html)

    def set_message(self, message: str) -> None:
        """Show a plain-text message instead of a chart."""
        self.figure = None
        self.html = ""
        if self._web:
            self._load_html(
                "<html><body style='font-family:sans-serif;color:#888;"
                f"padding:2em'>{message}</body></html>"
            )
        else:
            self._view.setText(message)

    def _load_html(self, html: str) -> None:
        """Load ``html`` via a temp file to avoid ``setHtml``'s ~2 MB limit."""
        if not self._web:
            self._view.setText("Charts require QtWebEngine.")
            return
        self._counter += 1
        path = Path(self._tmpdir.path()) / f"view_{self._counter}.html"
        path.write_text(html, encoding="utf-8")
        self._view.load(QUrl.fromLocalFile(str(path)))
