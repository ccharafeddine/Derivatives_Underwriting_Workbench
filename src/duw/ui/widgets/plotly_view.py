"""A Qt view that renders a plotly figure.

Wraps a :class:`QWebEngineView` and displays a plotly figure by rendering it to
self-contained HTML with plotly.js inlined, so charts work fully offline (no CDN
fetch). The rendered figure and HTML are kept as attributes so headless tests
can assert a figure was produced without inspecting pixels. If the web engine is
unavailable for any reason, the widget degrades to a text placeholder.
"""

from __future__ import annotations

import plotly.graph_objects as go
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlotlyView(QWidget):
    """Displays a plotly :class:`~plotly.graph_objects.Figure`."""

    def __init__(self) -> None:
        super().__init__()
        self.figure: go.Figure | None = None
        self.html: str = ""
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
        if self._web:
            self._view.setHtml(self.html)

    def set_message(self, message: str) -> None:
        """Show a plain-text message instead of a chart."""
        self.figure = None
        self.html = ""
        if self._web:
            self._view.setHtml(
                "<html><body style='font-family:sans-serif;color:#888;"
                f"padding:2em'>{message}</body></html>"
            )
        else:
            self._view.setText(message)
