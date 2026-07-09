"""Scenario stress-testing tab.

After a base analysis has run, apply market shocks (parallel rate shift, curve
steepen/flatten, FX move, credit-spread widening) and re-run to compare base vs
stressed exposure, CVA, and limit utilization side by side. The heavy re-run is
driven by the main window on the worker thread; this tab builds the
:class:`ScenarioSpec`, emits a request, and renders the comparison.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from duw.domain.results import AnalysisResults
from duw.risk.scenarios import ScenarioSpec
from duw.ui.widgets.charts import scenario_figure
from duw.ui.widgets.plotly_view import PlotlyView

# Named presets that fill the shock inputs. ``None`` keeps the current values.
_PRESETS: tuple[tuple[str, ScenarioSpec | None], ...] = (
    ("Custom", None),
    ("Rates +100 bp", ScenarioSpec("Rates +100bp", rate_shift_bps=100.0)),
    ("Rates -100 bp", ScenarioSpec("Rates -100bp", rate_shift_bps=-100.0)),
    ("Bear steepener", ScenarioSpec("Bear steepener", steepen_bps=150.0)),
    ("Credit crunch", ScenarioSpec("Credit crunch", spread_widen_pct=100.0)),
    (
        "Risk-off",
        ScenarioSpec(
            "Risk-off", rate_shift_bps=200.0, spread_widen_pct=50.0, fx_shock_pct=-10.0
        ),
    ),
)


def _money(x: float) -> str:
    return "—" if x is None or math.isnan(x) else f"{x:,.0f}"


def _pct_change(base: float, stressed: float) -> str:
    if base is None or stressed is None or math.isnan(base) or base == 0.0:
        return "—"
    return f"{stressed / base - 1:+.0%}"


class ScenarioTab(QWidget):
    """Shock inputs plus a base-vs-stressed comparison chart and table."""

    stressedRunRequested = Signal(object)  # ScenarioSpec

    def __init__(self) -> None:
        super().__init__()
        self._base: AnalysisResults | None = None
        self._has_inputs = False

        controls = self._build_controls()
        self.view = PlotlyView()
        self.table = self._build_table()
        self.commentary = QLabel(
            "Run a base analysis, then a stressed scenario to see a reading here."
        )
        self.commentary.setWordWrap(True)
        self.commentary.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        right_panel = QWidget()
        rp = QVBoxLayout(right_panel)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.addWidget(QLabel("<b>Base vs stressed</b>"))
        rp.addWidget(self.table)
        comm_box = QGroupBox("What this means")
        comm_layout = QVBoxLayout(comm_box)
        comm_layout.addWidget(self.commentary)
        comm_layout.addStretch(1)
        rp.addWidget(comm_box, 1)

        right = QSplitter()
        right.addWidget(self.view)
        right.addWidget(right_panel)
        right.setStretchFactor(0, 1)
        right.setSizes([760, 380])

        splitter = QSplitter()
        splitter.addWidget(controls)
        splitter.addWidget(right)
        splitter.setSizes([260, 1000])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.view.set_message("Run a base analysis, then a stressed scenario.")

    # -- construction ------------------------------------------------------ #
    def _build_controls(self) -> QWidget:
        box = QGroupBox("Market shocks")
        form = QFormLayout(box)

        self.preset = QComboBox()
        for name, _spec in _PRESETS:
            self.preset.addItem(name)
        self.preset.setCurrentText("Rates +100 bp")
        self.preset.currentIndexChanged.connect(self._on_preset)
        form.addRow("Preset", self.preset)

        self.rate_shift = self._shock_spin(-500.0, 500.0, " bps", 100.0)
        self.steepen = self._shock_spin(-500.0, 500.0, " bps", 0.0)
        self.fx_shock = self._shock_spin(-50.0, 50.0, " %", 0.0)
        self.spread_widen = self._shock_spin(-100.0, 500.0, " %", 0.0)
        form.addRow("Parallel rate shift", self.rate_shift)
        form.addRow("Steepener", self.steepen)
        form.addRow("FX shock", self.fx_shock)
        form.addRow("Spread widening", self.spread_widen)

        self.run_btn = QPushButton("Run stressed scenario")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._on_run)
        form.addRow(self.run_btn)

        self.status = QLabel("Run a base analysis first (Run Analysis).")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        return box

    @staticmethod
    def _shock_spin(
        lo: float, hi: float, suffix: str, default: float
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(0)
        spin.setSuffix(suffix)
        spin.setValue(default)
        return spin

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Metric", "Base", "Stressed", "Change"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # Cap the comparison table so the commentary below it stays visible.
        table.setMaximumHeight(260)
        return table

    # -- inputs ------------------------------------------------------------ #
    def _on_preset(self) -> None:
        spec = dict(_PRESETS)[self.preset.currentText()]
        if spec is None:
            return
        self.rate_shift.setValue(spec.rate_shift_bps)
        self.steepen.setValue(spec.steepen_bps)
        self.fx_shock.setValue(spec.fx_shock_pct)
        self.spread_widen.setValue(spec.spread_widen_pct)

    def current_spec(self) -> ScenarioSpec:
        """The scenario described by the current shock inputs."""
        name = self.preset.currentText()
        return ScenarioSpec(
            name=name if name != "Custom" else "Custom scenario",
            rate_shift_bps=self.rate_shift.value(),
            steepen_bps=self.steepen.value(),
            fx_shock_pct=self.fx_shock.value(),
            spread_widen_pct=self.spread_widen.value(),
        )

    # -- run lifecycle (driven by the main window) ------------------------- #
    def set_base(self, results: AnalysisResults, has_inputs: bool) -> None:
        """Record the base run; enable stressing if the inputs can be re-run."""
        self._base = results
        self._has_inputs = has_inputs
        self.run_btn.setEnabled(has_inputs)
        self.view.set_figure(scenario_figure(results.exposure, results.exposure))
        self.status.setText(
            "Base ready — choose shocks and run a stressed scenario."
            if has_inputs
            else "Base ready (re-run from Run Analysis to enable stressing)."
        )

    def set_busy(self, busy: bool) -> None:
        """Disable the run button while any analysis is in flight."""
        self.run_btn.setEnabled(not busy and self._has_inputs)

    def set_stressed(self, stressed: AnalysisResults) -> None:
        """Render the base-vs-stressed comparison."""
        if self._base is None:
            return
        self.view.set_figure(scenario_figure(self._base.exposure, stressed.exposure))
        self._fill_table(self._base, stressed)
        self.commentary.setText(self._stress_commentary(self._base, stressed))
        self.status.setText("Stressed scenario complete.")

    def _stress_commentary(
        self, base: AnalysisResults, stressed: AnalysisResults
    ) -> str:
        name = self.current_spec().name
        parts = [f"Under '{name}':"]
        if base.exposure is not None and stressed.exposure is not None:
            parts.append(
                f"peak PFE moves from {_money(base.exposure.peak_pfe)} to "
                f"{_money(stressed.exposure.peak_pfe)} "
                f"({_pct_change(base.exposure.peak_pfe, stressed.exposure.peak_pfe)})."
            )
        if base.cva is not None and stressed.cva is not None:
            parts.append(
                f"CVA moves from {_money(base.cva.cva)} to "
                f"{_money(stressed.cva.cva)} "
                f"({_pct_change(base.cva.cva, stressed.cva.cva)})."
            )
        if base.limits is not None and stressed.limits is not None:
            if stressed.limits.breach and not base.limits.breach:
                parts.append(
                    "The trade is within limit at base but BREACHES under this "
                    "stress — a sign the limit has little cushion against a shock."
                )
            elif stressed.limits.breach:
                parts.append("The trade breaches the limit under this stress.")
            else:
                parts.append("The trade stays within limit even under this stress.")
        return " ".join(parts)

    def _on_run(self) -> None:
        if self._has_inputs:
            self.status.setText("Running stressed scenario…")
            self.stressedRunRequested.emit(self.current_spec())

    # -- comparison table -------------------------------------------------- #
    def _fill_table(self, base: AnalysisResults, stressed: AnalysisResults) -> None:
        rows: list[tuple[str, str, str, str]] = []

        if base.exposure is not None and stressed.exposure is not None:
            b, s = base.exposure, stressed.exposure
            rows.append(
                (
                    "Peak PFE (95%)",
                    _money(b.peak_pfe),
                    _money(s.peak_pfe),
                    _pct_change(b.peak_pfe, s.peak_pfe),
                )
            )
            rows.append(
                ("EPE", _money(b.epe), _money(s.epe), _pct_change(b.epe, s.epe))
            )
        if base.cva is not None and stressed.cva is not None:
            rows.append(
                (
                    "CVA",
                    _money(base.cva.cva),
                    _money(stressed.cva.cva),
                    _pct_change(base.cva.cva, stressed.cva.cva),
                )
            )
            rows.append(("BCVA", _money(base.cva.bcva), _money(stressed.cva.bcva), "—"))
        if base.limits is not None and stressed.limits is not None:
            bl, sl = base.limits, stressed.limits
            rows.append(
                (
                    "Utilization",
                    f"{bl.utilization:.0%}",
                    f"{sl.utilization:.0%}",
                    f"{(sl.utilization - bl.utilization) * 100:+.0f} pp",
                )
            )
            rows.append(
                (
                    "Breach",
                    "yes" if bl.breach else "no",
                    "yes" if sl.breach else "no",
                    "",
                )
            )

        self.table.setRowCount(len(rows))
        for r, (metric, base_v, stressed_v, change) in enumerate(rows):
            for c, value in enumerate((metric, base_v, stressed_v, change)):
                self.table.setItem(r, c, QTableWidgetItem(value))
