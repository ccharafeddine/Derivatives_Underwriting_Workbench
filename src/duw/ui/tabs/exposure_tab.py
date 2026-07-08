"""Exposure analytics tab.

Renders the EE / EPE line, the PFE(95/99) cone, and the peak-PFE callout from a
completed run's :class:`ExposureProfile`, with the headline metrics beside it.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from duw.domain.results import AnalysisResults
from duw.ui.widgets.charts import exposure_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


class ExposureTab(QWidget):
    """Chart of the exposure cone plus a metrics summary."""

    def __init__(self) -> None:
        super().__init__()
        self.view = PlotlyView()
        self.table = MetricsTable()
        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(self.table)
        splitter.setSizes([820, 300])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.view.set_message("Run an analysis to see the exposure profile.")

    def set_results(self, results: AnalysisResults) -> None:
        """Render the exposure profile from ``results``."""
        exposure = results.exposure
        self.view.set_figure(exposure_figure(exposure))
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
