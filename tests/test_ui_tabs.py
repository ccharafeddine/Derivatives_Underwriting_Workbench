"""UI input-tab tests (Session 8). Headless via QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

import pytest

from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    FxDirection,
    FXForward,
    SwapDirection,
)
from duw.ui.app_state import AppState
from duw.ui.main_window import MainWindow
from duw.ui.tabs.counterparty_tab import CounterpartyTab
from duw.ui.tabs.trade_tab import TradeTab


# --------------------------------------------------------------------------- #
# Trade tab
# --------------------------------------------------------------------------- #
def test_trade_tab_builds_irs(qapp) -> None:
    tab = TradeTab()
    tab.product.setCurrentIndex(0)  # IRS
    tab.notional.setValue(25_000_000.0)
    tab.currency.setCurrentText("USD")
    tab.irs_fixed_rate.setValue(4.5)
    tab.irs_direction.setCurrentIndex(0)  # Pay fixed
    trade = tab.build_trade()
    assert isinstance(trade, IRS)
    assert trade.notional == 25_000_000.0
    assert trade.fixed_rate == pytest.approx(0.045)  # percent -> decimal
    assert trade.direction is SwapDirection.PAY_FIXED
    assert tab.is_valid()


def test_trade_tab_builds_fx_forward(qapp) -> None:
    tab = TradeTab()
    tab.product.setCurrentIndex(1)  # FX forward
    tab.fx_base.setCurrentText("EUR")
    tab.fx_quote.setCurrentText("USD")
    tab.fx_rate.setValue(1.1000)
    tab.fx_direction.setCurrentIndex(1)  # Sell base
    trade = tab.build_trade()
    assert isinstance(trade, FXForward)
    assert trade.base_currency == "EUR"
    assert trade.quote_currency == "USD"
    assert trade.currency == "EUR"  # notional is in the base currency
    assert trade.contract_rate == pytest.approx(1.10)
    assert trade.direction is FxDirection.SELL_BASE


def test_trade_tab_builds_cds(qapp) -> None:
    tab = TradeTab()
    tab.product.setCurrentIndex(2)  # CDS
    tab.cds_reference.setText("GLOBEX")
    tab.cds_spread.setValue(150.0)  # bps
    tab.cds_recovery.setValue(35.0)
    tab.cds_direction.setCurrentIndex(0)  # Buy protection
    trade = tab.build_trade()
    assert isinstance(trade, CDS)
    assert trade.reference_entity == "GLOBEX"
    assert trade.spread == pytest.approx(0.015)  # bps -> decimal
    assert trade.recovery_rate == pytest.approx(0.35)
    assert trade.direction is CdsDirection.BUY_PROTECTION


def test_trade_tab_rejects_maturity_before_trade_date(qapp) -> None:
    from PySide6.QtCore import QDate

    tab = TradeTab()
    tab.trade_date.setDate(QDate(2025, 6, 30))
    tab.maturity_date.setDate(QDate(2024, 6, 30))  # before trade date
    assert tab.build_trade() is None
    assert not tab.is_valid()


def test_trade_tab_rejects_zero_notional(qapp) -> None:
    tab = TradeTab()
    tab.notional.setValue(0.0)
    assert tab.build_trade() is None


def test_trade_tab_fx_rejects_same_currency(qapp) -> None:
    tab = TradeTab()
    tab.product.setCurrentIndex(1)
    tab.fx_base.setCurrentText("USD")
    tab.fx_quote.setCurrentText("USD")
    assert tab.build_trade() is None


def test_trade_tab_pushes_to_app_state(qapp) -> None:
    state = AppState()
    tab = TradeTab(state)
    tab.notional.setValue(12_000_000.0)  # triggers a refresh
    assert state.trade is not None
    assert state.trade.notional == 12_000_000.0


# --------------------------------------------------------------------------- #
# Counterparty tab
# --------------------------------------------------------------------------- #
def test_counterparty_tab_selects_seed(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.selector.setCurrentIndex(0)  # first seed counterparty
    cp = tab.build_counterparty()
    assert cp is not None
    assert cp.counterparty_id == state.counterparties[0].counterparty_id
    assert cp.financials is not None
    assert cp.financials.total_assets > 0.0


def test_counterparty_tab_custom_entry(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.selector.setCurrentIndex(tab.selector.count() - 1)  # "Custom…"
    tab.name.setText("Newco Ltd")
    tab.sector.setText("Retail")
    tab._fin_spins["total_assets"].setValue(1500.0)
    tab._fin_spins["total_liabilities"].setValue(600.0)
    cp = tab.build_counterparty()
    assert cp is not None
    assert cp.name == "Newco Ltd"
    assert cp.counterparty_id == "CP-CUSTOM"
    assert cp.financials.total_assets == 1500.0


def test_counterparty_tab_rejects_empty_name(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.selector.setCurrentIndex(tab.selector.count() - 1)  # custom
    tab.name.setText("")
    assert tab.build_counterparty() is None


def test_counterparty_tab_pushes_to_app_state(qapp) -> None:
    state = AppState()
    tab = CounterpartyTab(state)
    tab.selector.setCurrentIndex(0)
    assert state.counterparty is not None
    assert state.existing_set.counterparty_id == state.counterparty.counterparty_id


# --------------------------------------------------------------------------- #
# Main window integration
# --------------------------------------------------------------------------- #
def test_main_window_builds_all_tabs(qapp) -> None:
    window = MainWindow()
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert labels == [
        "Trade",
        "Counterparty",
        "Exposure",
        "Limits",
        "Collateral",
        "CVA",
        "Scenario",
        "Memo",
        "Pipeline",
    ]


def test_run_action_enables_only_when_ready(qapp) -> None:
    window = MainWindow()
    state = window.app_state
    # Selecting a seed counterparty and the default valid trade should enable Run.
    window.counterparty_tab.selector.setCurrentIndex(0)
    window.trade_tab._refresh()
    assert state.is_ready()
    assert window.run_action.isEnabled()

    # Clearing the trade disables it again.
    state.set_trade(None)
    window._update_run_enabled()
    assert not window.run_action.isEnabled()


# --------------------------------------------------------------------------- #
# Existing-trades book
# --------------------------------------------------------------------------- #
def _sample_trade(trade_id: str = "BK1") -> IRS:
    from datetime import date

    return IRS(
        trade_id=trade_id,
        counterparty_id="CP001",
        notional=5_000_000.0,
        currency="USD",
        trade_date=date(2025, 6, 30),
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.04,
        direction=SwapDirection.PAY_FIXED,
    )


def test_app_state_book_builds_existing_set(qapp) -> None:
    state = AppState()
    state.set_counterparty(state.counterparties[0])
    assert len(state.existing_set.trades) == 0
    trade = _sample_trade()
    state.add_to_book(trade)
    assert state.book == [trade]
    # The existing netting set reflects the book and the selected counterparty.
    assert state.existing_set.trades == (trade,)
    assert state.existing_set.counterparty_id == state.counterparty.counterparty_id
    state.remove_from_book(0)
    assert state.existing_set.trades == ()
    state.add_to_book(trade)
    state.clear_book()
    assert state.existing_set.trades == ()


def test_trade_tab_add_and_remove_from_book(qapp) -> None:
    state = AppState()
    tab = TradeTab(state)
    tab.notional.setValue(7_000_000.0)  # a valid trade
    assert tab.add_book_btn.isEnabled()
    tab._on_add_to_book()
    assert len(state.book) == 1
    assert tab.book_list.count() == 1  # list reflects the book via bookChanged
    tab.book_list.setCurrentRow(0)
    tab._on_remove_from_book()
    assert len(state.book) == 0
    assert tab.book_list.count() == 0


def test_run_inputs_include_the_book(qapp) -> None:
    state = AppState()
    state.set_counterparty(state.counterparties[0])
    state.set_trade(_sample_trade("PROPOSED"))
    state.add_to_book(_sample_trade("EXISTING1"))
    state.add_to_book(_sample_trade("EXISTING2"))
    counterparty, existing_set, proposed = state.run_inputs()
    assert proposed.trade_id == "PROPOSED"
    assert [t.trade_id for t in existing_set.trades] == ["EXISTING1", "EXISTING2"]
