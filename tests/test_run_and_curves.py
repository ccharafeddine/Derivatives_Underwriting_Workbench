"""Run Analysis toolbar and the Market tab's plotted curves.

Checks that Run Analysis is reachable as a toolbar button (not just a menu item)
and enabled out of the box, and that the Market tab plots the yield and
credit-spread curves from the snapshot rather than only tabulating them.
"""

from __future__ import annotations

from PySide6.QtWidgets import QToolBar

from duw.data.loader import load_market_snapshot
from duw.ui.app_state import AppState
from duw.ui.main_window import MainWindow
from duw.ui.tabs.market_tab import MarketTab
from duw.ui.widgets.charts import credit_curves_figure, yield_curves_figure


# --------------------------------------------------------------------------- #
# Curve figures (pure)
# --------------------------------------------------------------------------- #
def test_yield_curves_figure_has_a_series_per_currency() -> None:
    snap = load_market_snapshot()
    fig = yield_curves_figure(snap)
    names = {t.name for t in fig.data}
    assert names == set(snap.discount_curves)
    assert names  # not empty


def test_credit_curves_figure_has_a_series_per_issuer() -> None:
    snap = load_market_snapshot()
    fig = credit_curves_figure(snap)
    assert {t.name for t in fig.data} == set(snap.credit_curves)


def test_curve_figures_placeholder_when_empty() -> None:
    assert yield_curves_figure(None).data == ()
    assert credit_curves_figure(None).data == ()


# --------------------------------------------------------------------------- #
# Market tab plots the curves
# --------------------------------------------------------------------------- #
def test_market_tab_plots_the_curves(qapp) -> None:
    tab = MarketTab(AppState())
    assert tab.yield_view.figure is not None
    assert tab.credit_view.figure is not None
    assert len(tab.yield_view.figure.data) >= 1
    assert len(tab.credit_view.figure.data) >= 1


# --------------------------------------------------------------------------- #
# Run Analysis toolbar
# --------------------------------------------------------------------------- #
def test_run_analysis_is_on_the_toolbar_and_enabled(qapp) -> None:
    window = MainWindow()
    toolbars = window.findChildren(QToolBar)
    assert toolbars, "expected an analysis toolbar"
    actions = toolbars[0].actions()
    assert window.run_action in actions
    assert window.save_deal_action in actions
    # With the default trade and counterparty in place, Run is ready immediately.
    assert window.run_action.isEnabled()
