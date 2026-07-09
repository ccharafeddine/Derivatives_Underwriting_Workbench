"""Theme-aware charts.

The analytics charts render in their own web views, so they must be re-skinned to
match the app theme rather than staying a bright white card. These check the pure
skinning transform and that a PlotlyView re-skins on a theme switch.
"""

from __future__ import annotations

from duw.domain.results import ExposureProfile, LimitCheck
from duw.ui.widgets.charts import (
    apply_chart_theme,
    chart_palette,
    exposure_figure,
    limits_figure,
)
from duw.ui.widgets.plotly_view import PlotlyView

_EP = ExposureProfile(
    time_grid=[0.5, 1.0],
    ee=[100.0, 120.0],
    epe=110.0,
    pfe_95=[150.0, 180.0],
    pfe_99=[200.0, 230.0],
    peak_pfe=180.0,
    peak_pfe_time=1.0,
)


def test_apply_chart_theme_sets_background_and_font() -> None:
    dark = apply_chart_theme(exposure_figure(_EP), "dark")
    assert dark.layout.paper_bgcolor == chart_palette("dark")["paper"]
    assert dark.layout.font.color == chart_palette("dark")["font"]

    light = apply_chart_theme(exposure_figure(_EP), "light")
    assert light.layout.paper_bgcolor == chart_palette("light")["paper"]
    assert light.layout.paper_bgcolor != dark.layout.paper_bgcolor


def test_reference_line_recolors_across_theme_switches() -> None:
    lc = LimitCheck(
        current_peak_pfe=100.0,
        incremental_peak_pfe=50.0,
        proposed_peak_pfe=150.0,
        limit=140.0,
        utilization=1.07,
        breach=True,
        headroom=-10.0,
    )
    fig = limits_figure(lc)
    apply_chart_theme(fig, "dark")
    assert fig.layout.shapes[0].line.color == chart_palette("dark")["ref"]
    # Re-theming an already-themed figure re-matches the reference line.
    apply_chart_theme(fig, "light")
    assert fig.layout.shapes[0].line.color == chart_palette("light")["ref"]


def test_plotly_view_reskins_on_theme_change(qapp) -> None:
    view = PlotlyView()
    view.set_theme("dark")
    view.set_figure(exposure_figure(_EP))
    assert view.figure.layout.paper_bgcolor == chart_palette("dark")["paper"]
    view.set_theme("light")
    assert view.figure.layout.paper_bgcolor == chart_palette("light")["paper"]


def test_plotly_view_message_uses_theme_background(qapp) -> None:
    view = PlotlyView()
    view.set_theme("dark")
    view.set_message("Run an analysis to see the exposure profile.")
    assert view.figure is None
    # Switching theme with only a placeholder present does not raise.
    view.set_theme("light")
