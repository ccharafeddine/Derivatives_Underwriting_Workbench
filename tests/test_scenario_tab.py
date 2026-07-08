"""Scenario tab tests (v2). Headless via offscreen Qt."""

from __future__ import annotations

import plotly.graph_objects as go

from duw.domain.results import (
    AnalysisResults,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)
from duw.risk.scenarios import ScenarioSpec
from duw.ui.tabs.scenario_tab import ScenarioTab
from duw.ui.widgets.charts import scenario_figure

GRID = (0.0, 1.0, 2.0, 3.0)


def _results(peak: float, cva: float, util: float, breach: bool) -> AnalysisResults:
    return AnalysisResults(
        exposure=ExposureProfile(
            time_grid=GRID,
            ee=(0.0, peak * 0.2, peak * 0.25, peak * 0.1),
            epe=peak * 0.15,
            pfe_95=(0.0, peak * 0.8, peak, peak * 0.3),
            pfe_99=(0.0, peak, peak * 1.3, peak * 0.5),
            peak_pfe=peak,
            peak_pfe_time=2.0,
        ),
        cva=CVAResult(
            cva=cva,
            dva=cva * 0.5,
            bcva=cva * 0.5,
            lgd=0.6,
            time_grid=GRID,
            contributions=(0.0, cva * 0.4, cva * 0.4, cva * 0.2),
        ),
        limits=LimitCheck(
            limit=1_000_000.0,
            current_peak_pfe=0.0,
            proposed_peak_pfe=peak,
            incremental_peak_pfe=peak,
            utilization=util,
            headroom=1_000_000.0 - peak,
            breach=breach,
        ),
    )


def test_scenario_figure_overlays_base_and_stressed() -> None:
    base = _results(400_000, 3000, 0.4, False).exposure
    stressed = _results(900_000, 7000, 0.9, False).exposure
    fig = scenario_figure(base, stressed)
    assert isinstance(fig, go.Figure)
    names = {t.name for t in fig.data}
    assert {"Base EE", "Stressed EE", "Base PFE 95%", "Stressed PFE 95%"} <= names


def test_scenario_figure_empty_is_placeholder() -> None:
    fig = scenario_figure(None, None)
    assert len(fig.data) == 0


def test_preset_fills_shock_inputs(qapp) -> None:
    tab = ScenarioTab()
    tab.preset.setCurrentText("Risk-off")
    assert tab.rate_shift.value() == 200.0
    assert tab.spread_widen.value() == 50.0
    assert tab.fx_shock.value() == -10.0
    spec = tab.current_spec()
    assert spec.name == "Risk-off"
    assert spec.rate_shift_bps == 200.0


def test_run_disabled_until_base(qapp) -> None:
    tab = ScenarioTab()
    assert not tab.run_btn.isEnabled()
    tab.set_base(_results(400_000, 3000, 0.4, False), has_inputs=True)
    assert tab.run_btn.isEnabled()
    tab.set_busy(True)
    assert not tab.run_btn.isEnabled()
    tab.set_busy(False)
    assert tab.run_btn.isEnabled()


def test_run_emits_spec(qapp) -> None:
    tab = ScenarioTab()
    tab.set_base(_results(400_000, 3000, 0.4, False), has_inputs=True)
    tab.preset.setCurrentText("Rates +100 bp")
    captured: list = []
    tab.stressedRunRequested.connect(captured.append)
    tab._on_run()
    assert len(captured) == 1
    assert isinstance(captured[0], ScenarioSpec)
    assert captured[0].rate_shift_bps == 100.0


def test_stressed_fills_comparison_table(qapp) -> None:
    tab = ScenarioTab()
    base = _results(400_000, 3000, 0.4, False)
    stressed = _results(900_000, 7000, 1.2, True)
    tab.set_base(base, has_inputs=True)
    tab.set_stressed(stressed)
    assert tab.view.figure is not None
    assert tab.table.rowCount() >= 5
    # First row is Peak PFE with the +125% change.
    assert tab.table.item(0, 0).text() == "Peak PFE (95%)"
    assert "+125%" in tab.table.item(0, 3).text()
    # The breach row flips from no to yes.
    breach_row = next(
        r
        for r in range(tab.table.rowCount())
        if tab.table.item(r, 0).text() == "Breach"
    )
    assert tab.table.item(breach_row, 1).text() == "no"
    assert tab.table.item(breach_row, 2).text() == "yes"
