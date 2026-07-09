"""Collateral analytics tab.

Shows collateralized vs uncollateralized expected exposure with editable CSA
inputs (threshold, MTA, initial margin, MPoR). Editing the CSA and pressing
Apply recomputes collateral locally from the stored net-MtM cube — a light array
operation, so it runs on the UI thread without re-running the Monte Carlo.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from duw.domain.results import AnalysisResults, CollateralResult
from duw.risk.collateral import CSA, compute_collateral
from duw.ui.help import control_help
from duw.ui.widgets.analytics_panel import side_panel
from duw.ui.widgets.charts import collateral_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


def _amount_spin(default: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1e12)
    spin.setDecimals(0)
    spin.setGroupSeparatorShown(True)
    spin.setValue(default)
    return spin


class CollateralTab(QWidget):
    """Interactive CSA inputs over the collateralized exposure comparison."""

    def __init__(self) -> None:
        super().__init__()
        self._cube = None
        self._grid: tuple[float, ...] = ()

        self.threshold = _amount_spin(250_000.0)
        self.mta = _amount_spin(50_000.0)
        self.initial_margin = _amount_spin(0.0)
        self.mpor_days = QSpinBox()
        self.mpor_days.setRange(1, 60)
        self.mpor_days.setValue(10)
        self.collateral_currency = QComboBox()
        self.collateral_currency.addItems(("USD", "EUR"))
        self.fx_haircut = QDoubleSpinBox()
        self.fx_haircut.setRange(0.0, 30.0)
        self.fx_haircut.setDecimals(1)
        self.fx_haircut.setSuffix(" %")
        self.threshold.setToolTip(control_help("csa_threshold"))
        self.mta.setToolTip(control_help("csa_mta"))
        self.initial_margin.setToolTip(control_help("csa_im"))
        self.mpor_days.setToolTip(control_help("csa_mpor"))
        self.fx_haircut.setToolTip(control_help("csa_fx_haircut"))
        self.apply_button = QPushButton("Apply CSA")
        self.apply_button.clicked.connect(self._recompute)
        self.apply_button.setEnabled(False)

        csa_box = QGroupBox("Credit Support Annex")
        form = QFormLayout(csa_box)
        form.addRow("Threshold", self.threshold)
        form.addRow("MTA", self.mta)
        form.addRow("Initial margin", self.initial_margin)
        form.addRow("MPoR (days)", self.mpor_days)
        form.addRow("Collateral currency", self.collateral_currency)
        form.addRow("FX haircut", self.fx_haircut)
        form.addRow(self.apply_button)

        self.view = PlotlyView()
        self.table = MetricsTable()
        self.commentary = QLabel("Run an analysis to see a plain-English summary here.")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(csa_box)
        right_layout.addWidget(side_panel(self.table, self.commentary), 1)

        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([880, 360])
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)
        self.view.set_message("Run an analysis to see the collateral effect.")

    def current_csa(self) -> CSA:
        """The CSA described by the current inputs."""
        return CSA(
            threshold=self.threshold.value(),
            mta=self.mta.value(),
            initial_margin=self.initial_margin.value(),
            mpor_days=self.mpor_days.value(),
            collateral_currency=self.collateral_currency.currentText(),
            fx_haircut=self.fx_haircut.value() / 100.0,
        )

    def set_results(self, results: AnalysisResults) -> None:
        """Store the cube/grid and render collateral for the current CSA."""
        self._cube = results.net_mtm_cube
        self._grid = (
            results.collateral.time_grid if results.collateral is not None else ()
        )
        can_recompute = self._cube is not None and len(self._grid) > 0
        self.apply_button.setEnabled(can_recompute)
        if can_recompute:
            self._recompute()
        elif results.collateral is not None:
            self._render(results.collateral)
        else:
            self.view.set_message("Run an analysis to see the collateral effect.")
            self.table.set_metrics([])
            self.commentary.setText(
                "Run an analysis to see a plain-English summary here."
            )

    def _recompute(self) -> None:
        if self._cube is None or not self._grid:
            return
        result = compute_collateral(self._cube, self._grid, self.current_csa())
        self._render(result)

    def _render(self, collateral: CollateralResult) -> None:
        self.view.set_figure(collateral_figure(collateral))
        reduction = math.nan
        if not math.isnan(collateral.peak_pfe_uncollateralized) and (
            collateral.peak_pfe_uncollateralized > 0
        ):
            reduction = 1.0 - (
                collateral.peak_pfe_collateralized
                / collateral.peak_pfe_uncollateralized
            )
        rows = [
            (
                "Peak PFE uncollateralized",
                _money(collateral.peak_pfe_uncollateralized),
            ),
            ("Peak PFE collateralized", _money(collateral.peak_pfe_collateralized)),
            (
                "PFE reduction",
                "—" if math.isnan(reduction) else f"{reduction:.0%}",
            ),
            ("MPoR (days)", str(collateral.mpor_days)),
        ]
        if collateral.fx_haircut:
            rows.append(
                (
                    f"FX haircut ({collateral.collateral_currency})",
                    f"{collateral.fx_haircut:.0%}",
                )
            )
        self.table.set_metrics(rows)
        self.commentary.setText(self._commentary(collateral, reduction))

    @staticmethod
    def _commentary(collateral: CollateralResult, reduction: float) -> str:
        if math.isnan(reduction) or reduction <= 0.005:
            return (
                "With these CSA terms, collateral has a negligible effect: the "
                "threshold is high enough that little or nothing is collateralized. "
                "Lower the threshold to secure more of the exposure."
            )
        return (
            f"Collateral cuts peak exposure by {reduction:.0%}, from "
            f"{_money(collateral.peak_pfe_uncollateralized)} to "
            f"{_money(collateral.peak_pfe_collateralized)}. The residual is what "
            f"can still build during the {collateral.mpor_days}-day margin period "
            "of risk (the gap before collateral is collected after a default). "
            "Lower the threshold to collateralize more; a longer MPoR leaves more "
            "residual exposure."
        )
