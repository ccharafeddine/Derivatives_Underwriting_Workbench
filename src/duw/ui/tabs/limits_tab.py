"""Limits analytics tab.

Shows the limit utilization bar (existing plus incremental peak PFE against the
limit), a breach banner, and the headline limit numbers.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from duw.domain.results import AnalysisResults
from duw.ui.widgets.charts import limits_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


class LimitsTab(QWidget):
    """Limit utilization chart, breach banner, and metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.banner = QLabel()
        self.banner.setObjectName("limit_banner")
        self.banner.setWordWrap(True)
        self.view = PlotlyView()
        self.table = MetricsTable()

        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(self.table)
        splitter.setSizes([820, 300])

        layout = QVBoxLayout(self)
        layout.addWidget(self.banner)
        layout.addWidget(splitter)
        self._set_banner(None)
        self.view.set_message("Run an analysis to see limit utilization.")

    def set_results(self, results: AnalysisResults) -> None:
        """Render the limit check from ``results``."""
        limits = results.limits
        self.view.set_figure(limits_figure(limits))
        self._set_banner(limits.breach if limits is not None else None)
        if limits is None:
            self.table.set_metrics([])
            return
        self.table.set_metrics(
            [
                ("Limit", _money(limits.limit)),
                ("Current peak PFE", _money(limits.current_peak_pfe)),
                ("Proposed peak PFE", _money(limits.proposed_peak_pfe)),
                ("Incremental peak PFE", _money(limits.incremental_peak_pfe)),
                ("Utilization", f"{limits.utilization:.0%}"),
                ("Headroom", _money(limits.headroom)),
            ]
        )

    def _set_banner(self, breach: bool | None) -> None:
        if breach is None:
            self.banner.setText("")
            self.banner.setStyleSheet("")
            return
        if breach:
            self.banner.setText("LIMIT BREACH — proposed trade exceeds the limit.")
            self.banner.setStyleSheet(
                "background:#fdecea;color:#b71c1c;padding:8px;font-weight:bold;"
            )
        else:
            self.banner.setText("Within limit.")
            self.banner.setStyleSheet(
                "background:#eaf5ea;color:#1b5e20;padding:8px;font-weight:bold;"
            )
