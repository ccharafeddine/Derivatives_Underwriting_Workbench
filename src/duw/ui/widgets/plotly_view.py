"""A Qt view that renders a plotly figure.

Wraps a :class:`QWebEngineView` and displays a plotly figure by rendering it to
self-contained HTML with plotly.js inlined, so charts work fully offline (no CDN
fetch). The rendered figure and HTML are kept as attributes so headless tests
can assert a figure was produced without inspecting pixels. If the web engine is
unavailable for any reason, the widget degrades to a text placeholder.

**Static fallback.** QtWebEngine can crash the whole process (a native
segfault, not a Python exception) on some GPU drivers and headless X servers.
:func:`static_charts_enabled` switches every view to static PNG charts drawn
with kaleido when ``DUW_STATIC_CHARTS=1`` is set, the app was launched with
``--static-charts``, or the previous session ended without a clean exit while
web charts were active (a crash marker left by :func:`mark_web_session`).

The HTML is loaded from a temporary file rather than via ``setHtml``:
``QWebEngineView.setHtml`` encodes the content into a ``data:`` URL and silently
fails above roughly 2 MB (a Chromium limit), and a plotly document with inlined
plotly.js is several megabytes. Loading a local file has no such limit.
"""

from __future__ import annotations

import os
from pathlib import Path

import plotly.graph_objects as go
from PySide6.QtCore import QByteArray, Qt, QTemporaryDir, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from duw.ui.theme import current_theme
from duw.ui.widgets.charts import apply_chart_theme, chart_palette

STATIC_ENV = "DUW_STATIC_CHARTS"


def _crash_marker() -> Path:
    return Path.home() / ".duw" / "webengine-session"


def previous_session_crashed() -> bool:
    """True if a web-chart session was left open (the process died)."""
    return _crash_marker().exists()


def static_charts_enabled() -> bool:
    """Whether charts should render as static images instead of QtWebEngine."""
    return os.environ.get(STATIC_ENV, "") == "1"


def mark_web_session(active: bool) -> None:
    """Create (``True``) or clear (``False``) the crash marker for this session."""
    marker = _crash_marker()
    try:
        if active:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(os.getpid()), encoding="utf-8")
        elif marker.exists():
            marker.unlink()
    except OSError:
        pass  # best effort: never block the app on the marker file


class PlotlyView(QWidget):
    """Displays a plotly :class:`~plotly.graph_objects.Figure`, theme-aware."""

    def __init__(self) -> None:
        super().__init__()
        self.figure: go.Figure | None = None
        self.html: str = ""
        self._theme = current_theme()
        self._message: str | None = None
        self._tmpdir = QTemporaryDir()
        self._counter = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view: QWidget
        self._static = static_charts_enabled()
        self._web = False
        if not self._static:
            try:
                from PySide6.QtWebEngineWidgets import QWebEngineView

                self._view = QWebEngineView()
                self._web = True
            except Exception:
                self._static = True
        if not self._web:
            self._view = QLabel("")
            self._view.setWordWrap(True)
            self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._view)

    def set_figure(self, figure: go.Figure) -> None:
        """Render ``figure`` into the view, skinned to the active theme."""
        self._message = None
        self.figure = apply_chart_theme(figure, self._theme)
        self.html = self._figure_html(self.figure)
        self._load_html(self.html)

    def _figure_html(self, figure: go.Figure) -> str:
        """Self-contained HTML that makes the plot fill the whole view height.

        Plotly's default document gives the graph a fixed height, which leaves the
        chart looking thin in a tall pane. Forcing the document and the graph div
        to full height (plus a responsive config) makes the chart use all the
        space it's given.
        """
        html = figure.to_html(
            include_plotlyjs="inline",
            full_html=True,
            default_height="100%",
            config={"responsive": True},
        )
        return html.replace(
            "<head>",
            "<head><style>html,body{height:100%;margin:0;padding:0;"
            "overflow:hidden}.plotly-graph-div{height:100%!important;"
            "width:100%!important}</style>",
            1,
        )

    def set_message(self, message: str) -> None:
        """Show a plain-text message instead of a chart, on the themed ground."""
        self.figure = None
        self.html = ""
        self._message = message
        if self._web:
            self._load_html(self._message_html(message))
        else:
            self._view.setText(message)

    def set_theme(self, theme: str) -> None:
        """Re-skin the current figure (or placeholder) for ``theme`` and redraw."""
        self._theme = theme
        if self.figure is not None:
            apply_chart_theme(self.figure, theme)
            self.html = self._figure_html(self.figure)
            self._load_html(self.html)
        elif self._message is not None and self._web:
            self._load_html(self._message_html(self._message))

    def _message_html(self, message: str) -> str:
        palette = chart_palette(self._theme)
        return (
            f"<html><body style='margin:0;font-family:sans-serif;"
            f"background:{palette['paper']};color:{palette['muted']};"
            f"padding:2em'>{message}</body></html>"
        )

    def _render_static(self) -> None:
        """Draw the current figure as a PNG (kaleido) into the label."""
        if self.figure is None:
            self._view.setText(self._message or "")
            return
        try:
            png = self.figure.to_image(
                format="png",
                width=max(self.width(), 480),
                height=max(self.height(), 320),
            )
        except Exception:  # kaleido missing or failed
            self._view.setText(
                "Static charts need the 'export' extra (kaleido); "
                "the numbers are in the table alongside."
            )
            return
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(png))
        self._view.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if not self._web and self.figure is not None:
            self._render_static()

    def _load_html(self, html: str) -> None:
        """Load ``html`` via a temp file to avoid ``setHtml``'s ~2 MB limit."""
        if not self._web:
            self._render_static()
            return
        self._counter += 1
        path = Path(self._tmpdir.path()) / f"view_{self._counter}.html"
        path.write_text(html, encoding="utf-8")
        self._view.load(QUrl.fromLocalFile(str(path)))
