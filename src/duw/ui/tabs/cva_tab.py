"""CVA analytics tab.

Shows the per-interval CVA contribution chart and the CVA / DVA / BCVA totals.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from duw.domain.results import AnalysisResults
from duw.ui.widgets.charts import cva_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


class CvaTab(QWidget):
    """CVA contribution chart plus the adjustment totals."""

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
        self.view.set_message("Run an analysis to see the CVA breakdown.")

    def set_results(self, results: AnalysisResults) -> None:
        """Render the CVA result from ``results``."""
        cva = results.cva
        self.view.set_figure(cva_figure(cva))
        if cva is None:
            self.table.set_metrics([])
            return
        self.table.set_metrics(
            [
                ("CVA", _money(cva.cva)),
                ("DVA", _money(cva.dva)),
                ("BCVA", _money(cva.bcva)),
                ("LGD", f"{cva.lgd:.0%}" if not math.isnan(cva.lgd) else "—"),
            ]
        )
