"""Sensitivities tab.

On demand, computes DV01 / CS01 / FX delta of peak PFE and CVA by bump-and-
reprice (four pipelines with common random numbers) and shows them in a table.
The compute runs off the UI thread; this tab only requests it and renders the
result. Qt lives here.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from duw.risk.sensitivities import Sensitivities
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


class SensitivitiesTab(QWidget):
    """Bump-and-reprice sensitivities of peak PFE and CVA."""

    computeRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.compute_btn = QPushButton("Compute sensitivities")
        self.compute_btn.clicked.connect(self.computeRequested)
        self.compute_btn.setEnabled(False)
        self.status = QLabel(
            "Run an analysis, then compute DV01 / CS01 / FX delta by bump-and-reprice."
        )
        self.status.setWordWrap(True)

        controls = QHBoxLayout()
        controls.addWidget(self.compute_btn)
        controls.addWidget(self.status)
        controls.addStretch(1)

        self.table = MetricsTable()

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addStretch(1)

    def set_ready(self, ready: bool) -> None:
        """Enable the compute button once a run's inputs are available."""
        self.compute_btn.setEnabled(ready)

    def set_busy(self, busy: bool) -> None:
        self.compute_btn.setEnabled(not busy)
        if busy:
            self.status.setText("Computing sensitivities (four repricings)…")

    def set_result(self, sens: Sensitivities | None) -> None:
        self.compute_btn.setEnabled(True)
        if sens is None:
            self.status.setText(
                "<span style='color:#c62828'>Could not compute sensitivities.</span>"
            )
            self.table.set_metrics([])
            return
        self.status.setText(
            f"Bumps: rates +{sens.rate_bump_bps:g}bp, spreads "
            f"+{sens.spread_bump_bps:g}bp, FX +{sens.fx_bump_pct:g}%."
        )
        self.table.set_metrics(
            [
                ("DV01 — peak PFE (per 1bp)", _money(sens.dv01_pfe)),
                ("DV01 — CVA (per 1bp)", _money(sens.dv01_cva)),
                ("CS01 — CVA (per 1bp)", _money(sens.cs01_cva)),
                ("FX delta — peak PFE (per 1%)", _money(sens.fx_delta_pfe)),
                ("FX delta — CVA (per 1%)", _money(sens.fx_delta_cva)),
            ]
        )
