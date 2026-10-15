"""Seasoned-swap fixings input, day-count controls, and the static-chart fallback."""

from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
from PySide6.QtCore import QDate

from duw.domain.instruments import IRS, DayCount, SwapDirection
from duw.scenario.io import _trade_from_dict, _trade_to_dict
from duw.store.deals import trade_from_dict, trade_to_dict
from duw.ui.app_state import AppState
from duw.ui.tabs.trade_tab import TradeTab
from duw.ui.widgets import plotly_view

SEASONED = IRS(
    trade_id="S1",
    counterparty_id="CP001",
    notional=1e7,
    currency="USD",
    trade_date=date(2024, 4, 1),
    maturity_date=date(2029, 4, 2),
    fixed_rate=0.043,
    direction=SwapDirection.PAY_FIXED,
    fixed_day_count=DayCount.ACT_365,
    current_fixing=0.0525,
)


def test_current_fixing_round_trips_through_scenarios_and_deals() -> None:
    assert _trade_from_dict(_trade_to_dict(SEASONED)) == SEASONED
    assert trade_from_dict(trade_to_dict(SEASONED)) == SEASONED
    unfixed = _trade_to_dict(SEASONED) | {"current_fixing": None}
    assert _trade_from_dict(unfixed).current_fixing is None


def test_trade_tab_builds_fixing_and_day_counts(qapp) -> None:
    tab = TradeTab(AppState())
    tab.load_trade(SEASONED)
    trade, error = tab._build()
    assert error == ""
    assert trade.current_fixing == SEASONED.current_fixing
    assert trade.fixed_day_count is DayCount.ACT_365
    assert trade.float_day_count is DayCount.ACT_360
    assert "Current fixing: 5.250%" in tab.summary.text()


def test_trade_tab_flags_seasoned_swap_without_fixing(qapp) -> None:
    tab = TradeTab(AppState())
    tab.trade_date.setDate(QDate(2024, 4, 1))
    assert "Seasoned swap" in tab.status.text()
    tab.irs_fixing_known.setChecked(True)
    assert "Seasoned swap" not in tab.status.text()
    assert tab._build()[0].current_fixing is not None


def test_static_chart_mode_skips_webengine(qapp, monkeypatch) -> None:
    monkeypatch.setenv(plotly_view.STATIC_ENV, "1")
    view = plotly_view.PlotlyView()
    assert view._web is False
    view.resize(600, 400)
    view.set_figure(go.Figure(go.Scatter(x=[0, 1], y=[1, 2])))
    # Either a rendered pixmap (kaleido present) or an explanatory message.
    assert view._view.pixmap() is not None or view._view.text()
    assert view.figure is not None


def test_crash_marker_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(plotly_view.Path, "home", lambda: tmp_path)
    assert not plotly_view.previous_session_crashed()
    plotly_view.mark_web_session(True)
    assert plotly_view.previous_session_crashed()
    plotly_view.mark_web_session(False)
    assert not plotly_view.previous_session_crashed()
