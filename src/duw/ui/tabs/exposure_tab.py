"""Exposure analytics tab.

Renders the EE / EPE line, the PFE(95/99) cone, and the peak-PFE callout from a
completed run's :class:`ExposureProfile`, with the headline metrics and a
plain-English reading of them beside it.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from duw.domain.results import AnalysisResults
from duw.reports.interpreter import interpret_exposure
from duw.ui.widgets.analytics_panel import side_panel
from duw.ui.widgets.charts import exposure_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


class ExposureTab(QWidget):
    """Chart of the exposure cone plus a metrics summary and commentary."""

    def __init__(self) -> None:
        super().__init__()
        self.view = PlotlyView()
        self.table = MetricsTable()
        self.commentary = QLabel("Run an analysis to see a plain-English summary here.")

        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(side_panel(self.table, self.commentary))
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([920, 340])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.view.set_message("Run an analysis to see the exposure profile.")

    def set_results(self, results: AnalysisResults) -> None:
        """Render the exposure profile from ``results``."""
        exposure = results.exposure
        self.view.set_figure(exposure_figure(exposure))
        self.commentary.setText(interpret_exposure(results))
        if exposure is None:
            self.table.set_metrics([])
            return
        self.table.set_metrics(
            [
                ("EPE", _money(exposure.epe)),
                ("Peak PFE (95%)", _money(exposure.peak_pfe)),
                ("Peak PFE time", f"{exposure.peak_pfe_time:.2f}y"),
                (
                    "Max PFE (99%)",
                    _money(max(exposure.pfe_99) if exposure.pfe_99 else math.nan),
                ),
                ("Grid dates", str(len(exposure.time_grid))),
            ]
        )
