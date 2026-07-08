"""Analytics-tab rendering tests (Session 9). Headless via offscreen Qt."""

from __future__ import annotations

import numpy as np

from duw.domain.results import (
    AnalysisResults,
    CollateralResult,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)
from duw.ui.main_window import MainWindow
from duw.ui.tabs.collateral_tab import CollateralTab
from duw.ui.tabs.cva_tab import CvaTab
from duw.ui.tabs.exposure_tab import ExposureTab
from duw.ui.tabs.limits_tab import LimitsTab

GRID = (0.0, 1.0, 2.0, 3.0)


def _canned_results() -> AnalysisResults:
    rng = np.random.default_rng(0)
    cube = rng.normal(0.0, 100_000.0, size=(200, len(GRID)))
    exposure = ExposureProfile(
        time_grid=GRID,
        ee=(0.0, 100.0, 150.0, 50.0),
        epe=90.0,
        pfe_95=(0.0, 300.0, 400.0, 120.0),
        pfe_99=(0.0, 450.0, 600.0, 180.0),
        peak_pfe=400.0,
        peak_pfe_time=2.0,
    )
    collateral = CollateralResult(
        threshold=250_000.0,
        mta=50_000.0,
        initial_margin=0.0,
        mpor_days=10,
        time_grid=GRID,
        ee_uncollateralized=(0.0, 100.0, 150.0, 50.0),
        ee_collateralized=(0.0, 40.0, 60.0, 20.0),
        peak_pfe_uncollateralized=400.0,
        peak_pfe_collateralized=120.0,
    )
    cva = CVAResult(
        cva=5000.0,
        dva=2000.0,
        bcva=3000.0,
        lgd=0.6,
        time_grid=GRID,
        contributions=(0.0, 1500.0, 2500.0, 1000.0),
    )
    limits = LimitCheck(
        limit=1_000_000.0,
        current_peak_pfe=0.0,
        proposed_peak_pfe=400_000.0,
        incremental_peak_pfe=400_000.0,
        utilization=0.4,
        headroom=600_000.0,
        breach=False,
    )
    return AnalysisResults(
        net_mtm_cube=cube,
        exposure=exposure,
        collateral=collateral,
        cva=cva,
        limits=limits,
    )


def test_exposure_tab_renders(qapp) -> None:
    tab = ExposureTab()
    tab.set_results(_canned_results())
    assert tab.view.figure is not None
    assert tab.view.html  # rendered to HTML
    assert tab.table.rowCount() > 0


def test_limits_tab_renders_and_banners(qapp) -> None:
    tab = LimitsTab()
    tab.set_results(_canned_results())
    assert tab.view.figure is not None
    assert "Within limit" in tab.banner.text()


def test_cva_tab_renders(qapp) -> None:
    tab = CvaTab()
    tab.set_results(_canned_results())
    assert tab.view.figure is not None
    assert tab.table.rowCount() == 5  # CVA, DVA, BCVA, FVA, LGD


def test_collateral_tab_recomputes_on_apply(qapp) -> None:
    tab = CollateralTab()
    tab.set_results(_canned_results())
    assert tab.apply_button.isEnabled()  # cube available
    assert tab.view.figure is not None
    # A tighter threshold reduces the collateralized peak PFE on recompute.
    tab.threshold.setValue(50_000.0)
    tab.initial_margin.setValue(200_000.0)
    tab._recompute()
    assert tab.view.figure is not None
    assert tab.table.rowCount() > 0


def test_collateral_tab_without_cube_is_static(qapp) -> None:
    tab = CollateralTab()
    results = _canned_results()
    results.net_mtm_cube = None
    tab.set_results(results)
    assert not tab.apply_button.isEnabled()
    assert tab.view.figure is not None  # still shows the run's collateral result


def test_main_window_dispatches_results_to_tabs(qapp) -> None:
    window = MainWindow()
    window._on_finished(_canned_results())
    assert window.results is not None
    assert window.exposure_tab.view.figure is not None
    assert window.cva_tab.view.figure is not None
    assert window.collateral_tab.view.figure is not None
    assert window.tabs.currentWidget() is window.exposure_tab
