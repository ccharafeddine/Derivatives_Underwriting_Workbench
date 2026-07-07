"""Domain-model construction tests (Session 1)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from duw.domain.counterparty import Counterparty, CreditProfile, Financials
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    Frequency,
    FxDirection,
    FXForward,
    NettingSet,
    SwapDirection,
    Trade,
)
from duw.domain.market import CreditCurve, MarketSnapshot, YieldCurve
from duw.domain.results import (
    AnalysisResults,
    CollateralResult,
    CVAResult,
    ExposureProfile,
    LimitCheck,
    MemoResult,
)


def _sample_irs() -> IRS:
    return IRS(
        trade_id="T1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=date(2025, 6, 30),
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )


def test_irs_construction_and_tenor() -> None:
    irs = _sample_irs()
    assert irs.product == "IRS"
    assert irs.fixed_frequency is Frequency.ANNUAL
    assert 4.9 < irs.tenor_years < 5.1


def test_fx_forward_construction() -> None:
    fx = FXForward(
        trade_id="T2",
        counterparty_id="CP001",
        notional=5_000_000.0,
        currency="EUR",
        trade_date=date(2025, 6, 30),
        maturity_date=date(2026, 6, 30),
        base_currency="EUR",
        quote_currency="USD",
        contract_rate=1.09,
        direction=FxDirection.BUY_BASE,
    )
    assert fx.product == "FXForward"
    assert fx.base_currency == "EUR"


def test_cds_construction() -> None:
    cds = CDS(
        trade_id="T3",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=date(2025, 6, 30),
        maturity_date=date(2030, 6, 30),
        reference_entity="ACME",
        direction=CdsDirection.BUY_PROTECTION,
        spread=0.012,
    )
    assert cds.product == "CDS"
    assert cds.recovery_rate == 0.4


def test_frequency_per_year() -> None:
    assert Frequency.QUARTERLY.per_year == 4
    assert Frequency.MONTHLY.per_year == 12


def test_trades_are_frozen() -> None:
    irs = _sample_irs()
    with pytest.raises(FrozenInstanceError):
        irs.notional = 1.0  # type: ignore[misc]


def test_netting_set_add_is_immutable() -> None:
    ns = NettingSet(netting_set_id="NS1", counterparty_id="CP001")
    assert len(ns) == 0
    ns2 = ns.add_trade(_sample_irs())
    # Original set is unchanged; add_trade returns a new set.
    assert len(ns) == 0
    assert len(ns2) == 1
    assert ns2.currencies == ("USD",)
    assert isinstance(ns2.trades[0], Trade)


def test_market_dataclasses() -> None:
    curve = YieldCurve(currency="USD", tenors=(1.0, 2.0), zero_rates=(0.04, 0.042))
    credit = CreditCurve(issuer="ACME", tenors=(1.0, 5.0), spreads=(0.008, 0.015))
    snap = MarketSnapshot(
        as_of=date(2025, 6, 30),
        discount_curves={"USD": curve},
        fx_spot={"EURUSD": 1.08},
        credit_curves={"ACME": credit},
        rate_vols={"USD": 0.01},
        fx_vols={"EURUSD": 0.09},
    )
    assert snap.curve("USD") is curve
    assert snap.credit("ACME") is credit
    assert snap.fx("EURUSD") == 1.08
    with pytest.raises(KeyError):
        snap.curve("JPY")


def test_yield_curve_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        YieldCurve(currency="USD", tenors=(1.0, 2.0), zero_rates=(0.04,))


def test_counterparty_and_financials() -> None:
    fin = Financials(
        total_assets=5000.0,
        total_liabilities=3000.0,
        current_assets=2000.0,
        current_liabilities=1200.0,
        retained_earnings=800.0,
        ebit=600.0,
        sales=4000.0,
        market_equity=2500.0,
        equity_volatility=0.30,
    )
    assert fin.working_capital == 800.0
    cp = Counterparty(
        counterparty_id="CP001",
        name="Acme",
        sector="Industrials",
        financials=fin,
    )
    assert cp.ticker is None
    assert cp.financials is fin


def test_credit_profile_empty_construction() -> None:
    profile = CreditProfile(counterparty_id="CP001")
    assert profile.merton_pd is None
    assert profile.pd_term_structure == ()


def test_result_containers_construct_empty() -> None:
    # Every sub-result must be constructible with no arguments (containers now,
    # filled by later sessions).
    ExposureProfile()
    CollateralResult()
    CVAResult()
    LimitCheck()
    MemoResult()


def test_analysis_results_aggregate() -> None:
    results = AnalysisResults()
    assert results.exposure is None
    results.log("step 0 done")
    results.exposure = ExposureProfile(time_grid=(1.0, 2.0), ee=(10.0, 20.0))
    assert results.messages == ["step 0 done"]
    assert results.exposure.ee == (10.0, 20.0)
