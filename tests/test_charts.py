"""Plotly figure-builder tests (Session 9). Qt-free."""

from __future__ import annotations

import plotly.graph_objects as go

from duw.domain.results import (
    CollateralResult,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)
from duw.ui.widgets.charts import (
    collateral_figure,
    cva_figure,
    exposure_figure,
    limits_figure,
)

GRID = (0.0, 1.0, 2.0, 3.0)


def test_exposure_figure_has_traces() -> None:
    exposure = ExposureProfile(
        time_grid=GRID,
        ee=(0.0, 100.0, 150.0, 50.0),
        epe=90.0,
        pfe_95=(0.0, 300.0, 400.0, 120.0),
        pfe_99=(0.0, 450.0, 600.0, 180.0),
        peak_pfe=400.0,
        peak_pfe_time=2.0,
    )
    fig = exposure_figure(exposure)
    assert isinstance(fig, go.Figure)
    names = {t.name for t in fig.data}
    assert {"EE", "PFE 95%", "PFE 99%"}.issubset(names)


def test_exposure_figure_empty_is_placeholder() -> None:
    fig = exposure_figure(None)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0
    assert fig.layout.annotations  # placeholder text present


def test_collateral_figure_has_two_series() -> None:
    collateral = CollateralResult(
        time_grid=GRID,
        ee_uncollateralized=(0.0, 100.0, 150.0, 50.0),
        ee_collateralized=(0.0, 40.0, 60.0, 20.0),
        peak_pfe_uncollateralized=400.0,
        peak_pfe_collateralized=120.0,
    )
    fig = collateral_figure(collateral)
    names = {t.name for t in fig.data}
    assert names == {"Uncollateralized", "Collateralized"}


def test_cva_figure_titles_with_totals() -> None:
    cva = CVAResult(
        cva=5000.0,
        dva=2000.0,
        bcva=3000.0,
        lgd=0.6,
        time_grid=GRID,
        contributions=(0.0, 1500.0, 2500.0, 1000.0),
    )
    fig = cva_figure(cva)
    assert "CVA" in fig.layout.title.text
    assert len(fig.data) == 1
    assert list(fig.data[0].y) == [0.0, 1500.0, 2500.0, 1000.0]


def test_limits_figure_marks_breach() -> None:
    breached = LimitCheck(
        limit=100_000.0,
        current_peak_pfe=60_000.0,
        proposed_peak_pfe=140_000.0,
        incremental_peak_pfe=80_000.0,
        utilization=1.4,
        headroom=-40_000.0,
        breach=True,
    )
    fig = limits_figure(breached)
    assert "BREACH" in fig.layout.title.text
    assert fig.layout.barmode == "stack"
