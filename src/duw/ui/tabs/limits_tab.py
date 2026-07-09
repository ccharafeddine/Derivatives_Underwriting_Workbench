"""Limits analytics tab.

Shows the limit utilization bar (existing plus incremental peak PFE against the
limit), a breach banner, and the headline limit numbers.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from duw.domain.results import AnalysisResults
from duw.reports.interpreter import interpret_limits
from duw.ui.widgets.analytics_panel import side_panel
from duw.ui.widgets.charts import limits_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


class LimitsTab(QWidget):
    """Limit utilization chart, breach banner, metrics, and commentary."""

    def __init__(self) -> None:
        super().__init__()
        self.banner = QLabel()
        self.banner.setObjectName("limit_banner")
        self.banner.setWordWrap(True)
        # Keep the chip one line tall; the chart/panel take the vertical space.
        self.banner.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.view = PlotlyView()
        self.table = MetricsTable()
        self.commentary = QLabel("Run an analysis to see a plain-English summary here.")

        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(side_panel(self.table, self.commentary))
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([920, 340])

        # Keep the status as a small chip sized to its text, not a full-width bar.
        banner_row = QHBoxLayout()
        banner_row.addWidget(self.banner)
        banner_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(banner_row)
        layout.addWidget(splitter, 1)  # chart/panel take the height, not the chip
        self._set_banner(None)
        self.view.set_message("Run an analysis to see limit utilization.")

    def set_results(self, results: AnalysisResults) -> None:
        """Render the limit check from ``results``."""
        limits = results.limits
        self.view.set_figure(limits_figure(limits))
        self._set_banner(limits.breach if limits is not None else None)
        self.commentary.setText(interpret_limits(results))
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
        # Semi-transparent tints so the chip reads on both the light and dark
        # themes rather than sitting as a bright block on a dark ground.
        if breach is None:
            self.banner.setText("")
            self.banner.setStyleSheet("")
            return
        if breach:
            self.banner.setText("⚠  LIMIT BREACH — proposed trade exceeds the limit")
            self.banner.setStyleSheet(
                "color:#e5534b; background:rgba(214,39,40,0.15);"
                "border:1px solid #d62728; border-radius:4px;"
                "padding:4px 12px; font-weight:bold;"
            )
        else:
            self.banner.setText("✓  Within limit")
            self.banner.setStyleSheet(
                "color:#2ea043; background:rgba(46,160,67,0.15);"
                "border:1px solid #2ca02c; border-radius:4px;"
                "padding:4px 12px; font-weight:bold;"
            )
