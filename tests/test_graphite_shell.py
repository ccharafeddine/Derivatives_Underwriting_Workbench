"""Graphite redesign: app shell, navigation, deal header, KPI strip, overview.

Widget tests for the Phase 2 layout. Every workflow page must stay reachable
from the grouped navigation; the deal header and KPI strip must follow the
deal; the overview must render the decision; the Graphite theme, its chart
recolouring and the one-time theme migration must behave.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import plotly.graph_objects as go
import pytest

from duw.config import KEY_THEME, KEY_THEME_MIGRATED, AppSettings
from duw.data.loader import load_market_snapshot
from duw.domain.counterparty import CreditProfile
from duw.domain.instruments import NettingSet
from duw.domain.results import (
    AnalysisResults,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)
from duw.examples import examples
from duw.ui import theme
from duw.ui.format import full_money, pct, short_money, tone
from duw.ui.main_window import PAGE_SUBTITLES, TAB_NAMES, MainWindow
from duw.ui.tabs.overview_tab import OverviewTab, deal_kpis, verdict_tone
from duw.ui.widgets.app_shell import (
    ASSETS,
    NAV_GROUPS,
    KpiStrip,
    LimitBar,
    NavPanel,
    app_icon,
)
from duw.ui.widgets.charts import apply_chart_theme, exposure_figure


def _results(*, breach: bool = False, util: float = 0.64) -> AnalysisResults:
    """A small, fully populated synthetic result for the deal views."""
    snap = load_market_snapshot()
    ex = examples()[0]
    trade = ex.trade
    book = replace(trade, trade_id="BOOK-1", notional=5e6)
    ns = NettingSet("NS-CP002", trade.counterparty_id, (book, trade))
    grid = tuple(i * 0.5 for i in range(11))
    ee = tuple(1e5 * math.sin(math.pi * t / 5.0) for t in grid)
    pfe = tuple(3 * v for v in ee)
    results = AnalysisResults(
        run_config={"n_paths": 2000, "n_steps": 12, "seed": 7, "lgd": 0.6},
        snapshot=snap,
        netting_set=ns,
        credit_profile=CreditProfile(
            counterparty_id=trade.counterparty_id,
            internal_grade="A",
            merton_pd=0.0021,
            altman_z=3.4,
            altman_zone="safe",
            distance_to_default=5.8,
        ),
        exposure=ExposureProfile(
            time_grid=grid,
            ee=ee,
            epe=5e4,
            pfe_95=pfe,
            pfe_99=tuple(1.3 * v for v in pfe),
            peak_pfe=max(pfe),
            peak_pfe_time=2.5,
        ),
        cva=CVAResult(cva=48_210.0, dva=12_930.0, bcva=35_280.0, fva=6_400.0, lgd=0.6),
        limits=LimitCheck(
            limit=6e6,
            current_peak_pfe=1.12e6,
            proposed_peak_pfe=util * 6e6,
            incremental_peak_pfe=util * 6e6 - 1.12e6,
            utilization=util,
            headroom=6e6 * (1 - util),
            breach=breach,
        ),
    )
    return results


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
def test_nav_covers_every_page_once() -> None:
    keys = [key for _group, entries in NAV_GROUPS for _label, key in entries]
    assert sorted(keys) == sorted(TAB_NAMES)
    assert len(keys) == len(set(keys))
    assert set(PAGE_SUBTITLES) == set(TAB_NAMES)


def test_every_page_is_reachable_from_the_nav(qapp) -> None:
    window = MainWindow()
    assert not window.tabs.tabBar().isVisible()
    for name in TAB_NAMES:
        item = window.nav._items[name]
        window.nav.list.setCurrentItem(item)  # what a click does
        assert window.current_page() == name
        assert window.page_header.title.text() == window.nav.label(name)
        assert window.page_header.subtitle.text() == PAGE_SUBTITLES[name]


def test_show_page_keeps_nav_in_sync(qapp) -> None:
    window = MainWindow()
    window.show_page("CVA")
    assert window.nav.current() == "CVA"
    assert window.nav.list.currentItem().text() == "XVA"
    window.tabs.setCurrentWidget(window.limits_tab)
    assert window.nav.current() == "Limits"


def test_group_headers_are_not_selectable(qapp) -> None:
    nav = NavPanel()
    for head in nav._headers:
        assert not head.flags()
    nav.list.setCurrentRow(0)  # the "DEAL" header
    assert nav.current() == "Overview"


def test_kpi_strip_hidden_on_non_deal_pages(qapp) -> None:
    window = MainWindow()
    window.show()
    window.show_page("Simulator")
    assert not window.kpi_strip.isVisible()
    window.show_page("Exposure")
    assert window.kpi_strip.isVisible()
    window.close()


# --------------------------------------------------------------------------- #
# Deal header
# --------------------------------------------------------------------------- #
def test_deal_header_follows_the_deal(qapp) -> None:
    window = MainWindow()
    ex = examples()[3]  # netted book: one existing trade
    window._load_example(ex)
    bar = window.top_bar
    assert not bar.example_tag.isHidden()
    assert ex.trade.product in bar.chip_trade.text()
    assert bar.chip_book.text() == "Book: 1 trade"
    assert window.app_state.counterparty.name in bar.chip_counterparty.toolTip()
    assert bar.snapshot_label.text().startswith("Snapshot ")


def test_header_chips_navigate(qapp) -> None:
    window = MainWindow()
    window.top_bar.chip_counterparty.click()
    assert window.current_page() == "Counterparty"
    window.top_bar.chip_trade.click()
    assert window.current_page() == "Trade"


def test_examples_button_offers_every_example(qapp) -> None:
    window = MainWindow()
    names = [a.text() for a in window.top_bar.examples_button.menu().actions()]
    assert names == [e.name for e in examples()]


# --------------------------------------------------------------------------- #
# KPI strip and overview
# --------------------------------------------------------------------------- #
def test_deal_kpis_values_and_tones() -> None:
    kpis = {name: (value, sub, t) for name, value, sub, t in deal_kpis(_results())}
    assert kpis["Limit use"][0] == "64%"
    assert kpis["CVA"][0] == "\u221248,210" and kpis["CVA"][2] == "neg"
    assert kpis["DVA"][0] == "+12,930" and kpis["DVA"][2] == "pos"
    assert kpis["FVA"][0] == "\u22126,400"
    assert kpis["Recommendation"][0] == "Approve"
    breach = {n: (v, t) for n, v, _s, t in deal_kpis(_results(breach=True, util=1.2))}
    assert breach["Recommendation"] == ("Decline", "neg")
    assert breach["Limit use"][1] == "neg"
    assert deal_kpis(None) == []


def test_kpi_strip_cells(qapp) -> None:
    strip = KpiStrip()
    assert [strip.cell(n).label.text() for n in KpiStrip.NAMES][0] == "PEAK PFE 95%"
    strip.set_metric("CVA", "−1", "x", "neg")
    assert strip.cell("CVA").value.text() == "−1"
    assert theme.tokens()["red"].lower() in strip.cell("CVA").value.styleSheet().lower()
    strip.clear()
    assert strip.cell("CVA").value.text() == "—"


def test_verdict_tone() -> None:
    assert verdict_tone("Approve") == "pos"
    assert verdict_tone("Approve with conditions") == "warn"
    assert verdict_tone("Decline") == "neg"
    assert verdict_tone(None) is None


def test_overview_renders_decision_and_netting_set(qapp) -> None:
    tab = OverviewTab()
    tab.set_results(_results())
    assert tab.verdict.text() == "Approve"
    assert tab.rationale.text()
    assert tab.trades.rowCount() == 2
    assert tab.trades.item(1, 0).text() == "NEW"
    assert tab.trades.item(0, 0).text() == "BOOK-1"
    # MtM column is right-aligned and priced (not the "—" fallback).
    assert tab.trades.item(1, 5).text() != "—"
    rows = dict(tab.counterparty_rows(_results()))
    assert rows["Internal rating"] == "A"
    assert "64% used" in tab.limit_text.text()
    assert tab.view.figure is not None


def test_overview_decline_on_breach(qapp) -> None:
    tab = OverviewTab()
    tab.set_results(_results(breach=True, util=1.3))
    assert tab.verdict.text() == "Decline"
    assert "BREACH" in tab.limit_text.text()


def test_limit_bar_paints(qapp) -> None:
    bar = LimitBar()
    bar.resize(300, 22)
    bar.set_values(1e6, 2e6, 6e6)
    img = bar.grab()
    assert not img.isNull()


def test_window_overview_and_kpis_after_results(qapp) -> None:
    window = MainWindow()
    window.results = _results()
    window._set_kpis(window.results)
    assert window.kpi_strip.cell("Limit use").value.text() == "64%"
    assert "2,000 paths" in window.run_info.text()


# --------------------------------------------------------------------------- #
# Theme, charts, assets, formatting
# --------------------------------------------------------------------------- #
def test_graphite_is_default_and_legacy_themes_remain() -> None:
    assert theme.THEMES[0] == "graphite" == theme.DEFAULT_THEME
    assert {"dark", "light"} <= set(theme.THEMES)
    qss = theme.stylesheet("graphite")
    assert "#2F6FEB" in qss and "#f2a007" not in qss.lower()
    assert "#f2a007" in theme.stylesheet("dark")  # amber kept as an option
    assert theme.normalize_theme("nope") == "graphite"


def test_theme_migration_runs_once(tmp_path) -> None:
    s = AppSettings(ini_path=str(tmp_path / "s.ini"))
    assert s.get_str(KEY_THEME) == "graphite"  # new default
    s.set(KEY_THEME, "dark")
    s.migrate_theme()
    assert s.get_str(KEY_THEME) == "graphite"
    assert s.get_bool(KEY_THEME_MIGRATED)
    s.set(KEY_THEME, "dark")  # an explicit later choice is respected
    s.migrate_theme()
    assert s.get_str(KEY_THEME) == "dark"


def test_theme_menu_lists_named_themes(qapp) -> None:
    window = MainWindow()
    labels = [a.text() for a in window._theme_group.actions()]
    assert labels == [theme.THEME_LABELS[t] for t in theme.THEMES]


def test_chart_traces_recolor_by_theme() -> None:
    fig = exposure_figure(_results().exposure)
    apply_chart_theme(fig, "graphite")
    by_name = {t.name: t for t in fig.data}
    assert by_name["EE"].line.color == "#E6EDF3"
    assert by_name["PFE 95%"].line.color == "#4C8DFF"
    assert fig.layout.paper_bgcolor == "#12161A"
    apply_chart_theme(fig, "dark")
    assert by_name["EE"].line.color != "#E6EDF3"
    apply_chart_theme(fig, "graphite")
    assert {t.line.color for t in fig.data if t.name == "EE"} == {"#E6EDF3"}


def test_untagged_traces_are_left_alone() -> None:
    fig = go.Figure(go.Scatter(x=[0, 1], y=[0, 1], line=dict(color="#123456")))
    apply_chart_theme(fig, "graphite")
    assert fig.data[0].line.color == "#123456"


def test_logo_assets_and_icon(qapp) -> None:
    for name in ("logo.svg", "logo_mark.svg", "logo.png", "app.ico"):
        assert (Path(ASSETS) / name).exists(), name
    assert "#14B8A6" in (Path(ASSETS) / "logo.svg").read_text().upper()
    assert not app_icon().isNull()
    assert not MainWindow().windowIcon().isNull()


@pytest.mark.parametrize(
    ("x", "short", "full"),
    [
        (3_860_000.0, "3.86M", "3,860,000"),
        (-48_210.0, "\u221248,210", "\u221248,210"),
        (482_000.0, "482K", "482,000"),
        (float("nan"), "—", "—"),
    ],
)
def test_format_helpers(x, short, full) -> None:
    assert short_money(x) == short
    assert full_money(x) == full


def test_format_signs_and_tone() -> None:
    assert short_money(1.5e6, signed=True) == "+1.50M"
    assert full_money(0.0, signed=True) == "0"
    assert pct(0.643) == "64%"
    assert tone(-1) == "neg" and tone(1) == "pos" and tone(0) is None


def test_static_chart_does_not_grow_its_view(qapp, monkeypatch) -> None:
    from duw.ui.widgets import plotly_view

    monkeypatch.setenv(plotly_view.STATIC_ENV, "1")
    view = plotly_view.PlotlyView()
    view.resize(400, 300)
    hint = view.minimumSizeHint()
    view.set_figure(exposure_figure(_results().exposure))
    assert view.minimumSizeHint().height() <= max(hint.height(), 1)
