"""Memo tab.

Previews the underwriting memo (rendered HTML with interactive charts) and
offers HTML / PDF / PPTX export. Rendering and export reuse the Qt-free
:mod:`duw.reports` engine; the tab only handles preview and file dialogs.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from duw.domain.results import AnalysisResults
from duw.reports.memo import (
    generate_memo,
    render_memo_html,
    write_memo_html,
    write_memo_pdf,
)


class MemoTab(QWidget):
    """Preview and export the underwriting memo."""

    def __init__(self) -> None:
        super().__init__()
        self.results: AnalysisResults | None = None
        self.preview_html: str = ""

        self.export_html_btn = QPushButton("Export HTML…")
        self.export_pdf_btn = QPushButton("Export PDF…")
        self.export_pptx_btn = QPushButton("Export PPTX…")
        for btn in (self.export_html_btn, self.export_pdf_btn, self.export_pptx_btn):
            btn.setEnabled(False)
        self.export_html_btn.clicked.connect(self._on_export_html)
        self.export_pdf_btn.clicked.connect(self._on_export_pdf)
        self.export_pptx_btn.clicked.connect(self._on_export_pptx)

        buttons = QHBoxLayout()
        buttons.addWidget(self.export_html_btn)
        buttons.addWidget(self.export_pdf_btn)
        buttons.addWidget(self.export_pptx_btn)
        buttons.addStretch(1)

        self._view: QWidget
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView

            self._view = QWebEngineView()
            self._web = True
        except Exception:
            from PySide6.QtWidgets import QTextBrowser

            self._view = QTextBrowser()
            self._web = False

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self._view)
        self._show_html(
            "<html><body style='font-family:sans-serif;color:#888;padding:2em'>"
            "Run an analysis to generate the underwriting memo.</body></html>"
        )

    def set_results(self, results: AnalysisResults) -> None:
        """Render the memo preview for ``results`` and enable export."""
        self.results = results
        self.preview_html = render_memo_html(results, include_charts=True)
        self._show_html(self.preview_html)
        for btn in (self.export_html_btn, self.export_pdf_btn, self.export_pptx_btn):
            btn.setEnabled(True)

    def _show_html(self, html: str) -> None:
        if self._web:
            self._view.setHtml(html)
        else:
            self._view.setHtml(html)

    # -- export ------------------------------------------------------------ #
    def _on_export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export memo (HTML)", "", "HTML (*.html)"
        )
        if path:
            self._export(lambda p: write_memo_html(self.results, p), path)

    def _on_export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export memo (PDF)", "", "PDF (*.pdf)"
        )
        if path:
            self._export(lambda p: write_memo_pdf(self.results, p), path)

    def _on_export_pptx(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export deck (PPTX)", "", "PPTX (*.pptx)"
        )
        if path:
            self._export(self._export_pptx, path)

    def _export_pptx(self, path: str) -> Path:
        out_dir = Path(path).parent
        result = generate_memo(
            self.results, out_dir, formats=("pptx",), basename=Path(path).stem
        )
        return Path(result.pptx_path) if result.pptx_path else Path(path)

    def _export(self, writer, path: str) -> None:
        if self.results is None:
            return
        try:
            writer(path)
        except Exception as exc:  # surface export failures without crashing
            QMessageBox.critical(self, "Export failed", str(exc))
