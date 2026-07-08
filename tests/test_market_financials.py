"""Market editor and live-financials tests (v2, track 3). Offscreen Qt."""

from __future__ import annotations

import pytest

from duw.domain.counterparty import Financials
from duw.ui.app_state import AppState
from duw.ui.tabs.counterparty_tab import CounterpartyTab
from duw.ui.tabs.market_tab import MarketTab


# --------------------------------------------------------------------------- #
# AppState snapshot
# --------------------------------------------------------------------------- #
def test_app_state_set_and_reset_snapshot(qapp) -> None:
    state = AppState()
    original_usd = state.snapshot.curve("USD").zero_rates
    changed: list = []
    state.snapshotChanged.connect(lambda: changed.append(True))

    from duw.domain.market import MarketSnapshot, YieldCurve

    bumped = MarketSnapshot(
        as_of=state.snapshot.as_of,
        discount_curves={
            "USD": YieldCurve("USD", (1.0, 5.0), (0.10, 0.11)),
        },
    )
    state.set_snapshot(bumped)
    assert state.snapshot.curve("USD").zero_rates == (0.10, 0.11)
    assert len(changed) == 1
    state.reset_snapshot()
    assert state.snapshot.curve("USD").zero_rates == original_usd
    assert len(changed) == 2


# --------------------------------------------------------------------------- #
# Market tab
# --------------------------------------------------------------------------- #
def test_market_tab_apply_edits_snapshot(qapp) -> None:
    state = AppState()
    tab = MarketTab(state)
    # Bump every USD zero-rate cell by 1 percentage point and apply.
    usd_table = tab._rate_tables["USD"]
    for r in range(usd_table.rowCount()):
        current = float(usd_table.item(r, 1).text())
        usd_table.item(r, 1).setText(f"{current + 1.0:g}")
    base = state.snapshot.curve("USD").zero_rates
    tab._apply()
    bumped = state.snapshot.curve("USD").zero_rates
    for r0, r1 in zip(base, bumped, strict=True):
        assert r1 == pytest.approx(r0 + 0.01)


def test_market_tab_edits_spreads(qapp) -> None:
    state = AppState()
    tab = MarketTab(state)
    issuer = next(iter(state.snapshot.credit_curves))
    table = tab._credit_tables[issuer]
    # Double the first spread (in bps).
    first = float(table.item(0, 1).text())
    table.item(0, 1).setText(f"{first * 2:g}")
    base_first = state.snapshot.credit(issuer).spreads[0]
    tab._apply()
    assert state.snapshot.credit(issuer).spreads[0] == pytest.approx(base_first * 2)


def test_market_tab_reset_repopulates(qapp) -> None:
    state = AppState()
    tab = MarketTab(state)
    usd_table = tab._rate_tables["USD"]
    usd_table.item(0, 1).setText("99")
    tab._apply()
    assert state.snapshot.curve("USD").zero_rates[0] == pytest.approx(0.99)
    state.reset_snapshot()  # tab rebuilds via snapshotChanged
    assert tab._rate_tables["USD"].item(0, 1).text() != "99"


# --------------------------------------------------------------------------- #
# Live financials fetch (offline behavior; no network)
# --------------------------------------------------------------------------- #
def _financials() -> Financials:
    return Financials(
        total_assets=9000.0,
        total_liabilities=4000.0,
        current_assets=5000.0,
        current_liabilities=2000.0,
        retained_earnings=3000.0,
        ebit=1800.0,
        sales=7000.0,
        market_equity=11000.0,
        equity_volatility=0.28,
    )


def test_fetch_result_populates_fields(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.selector.setCurrentIndex(tab.selector.count() - 1)  # custom
    tab.ticker.setText("AAPL")
    tab._on_fetched(_financials())  # simulate a successful async result
    assert tab._fin_spins["total_assets"].value() == 9000.0
    assert tab._fin_spins["market_equity"].value() == 11000.0
    assert "Loaded" in tab.fetch_status.text()


def test_fetch_failure_keeps_values(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.selector.setCurrentIndex(0)  # a seed with financials
    before = tab._fin_spins["total_assets"].value()
    tab.ticker.setText("NOPE")
    tab._on_fetched(None)  # simulate a failed async result
    assert tab._fin_spins["total_assets"].value() == before
    assert "Could not fetch" in tab.fetch_status.text()


def test_fetch_empty_ticker_is_noop(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.ticker.setText("")
    tab._on_fetch()  # must not start a fetch or raise
    assert "Enter a ticker" in tab.fetch_status.text()
